import json
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from llm.base import ChatMessage, LLMProvider
from llm.factory import create_llm_provider
from mcp_clients.uyuni_client import MCPToolDefinition, MCPToolResult, UyuniMCPClient


@dataclass(frozen=True)
class UIComponentCall:
    """Componente de Generative UI que el LLM ha decidido mostrar."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AgentResponse:
    """Respuesta del agente: texto + llamadas a componentes CopilotKit GenUI."""

    text: str
    ui_calls: list[UIComponentCall] = field(default_factory=list)
    # Se conserva el campo del experimento AG-UI anterior para no romper
    # consumidores/tests antiguos. En esta variante CopilotKit queda vacío.
    visualizations: list[dict[str, Any]] = field(default_factory=list)


class ChatAgent:
    """
    Agente conversacional principal del backend.

    Flujo optimizado (experimento de 2 llamadas LLM para consultas Uyuni):
    1. Recibe mensajes desde AG-UI.
    2. Convierte los mensajes a ChatMessage.
    3. Descubre/cachea las tools de lectura reales del MCP.
    4. Una única llamada LLM decide si usar Uyuni y, en caso afirmativo,
       selecciona la tool y construye sus argumentos.
    5. El backend valida la decisión y ejecuta la tool MCP.
    6. Una segunda llamada LLM redacta la respuesta final con el resultado real.
    7. Si no hace falta MCP, una segunda llamada responde normalmente.
    """

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        uyuni_client: UyuniMCPClient | None = None,
    ):
        self.llm_provider = llm_provider or create_llm_provider()
        self.uyuni_client = uyuni_client or UyuniMCPClient()

        # Cache del catálogo MCP para no volver a arrancar Docker solo para
        # descubrir las mismas tools en cada turno. Se rellena en el primer uso.
        self._cached_uyuni_tools: list[MCPToolDefinition] | None = None

    async def generate_response(self, agui_messages: Sequence[Any]) -> str:
        """
        Contrato textual original. Se conserva para no romper tests ni otros
        consumidores que esperan exactamente un ``str``.
        """

        response = await self.generate_rich_response(agui_messages)
        return response.text

    async def generate_rich_response(
        self,
        agui_messages: Sequence[Any],
        frontend_tools: Sequence[Any] | None = None,
    ) -> AgentResponse:
        """
        Punto de entrada usado por AG-UI.

        En el modo optimizado se unifican router + selector + argumentos en
        una única inferencia. Para una consulta Uyuni el flujo queda:

            LLM decisión completa -> MCP -> LLM respuesta final

        Es decir, dos llamadas LLM en lugar de hasta cuatro.
        """

        chat_messages = [
            self._convert_agui_message_to_chat_message(message)
            for message in agui_messages
        ]

        last_user_message = self._get_last_user_message(chat_messages)

        # CopilotChat puede iniciar una ejecución al montar el componente aunque
        # aún no exista ningún mensaje del usuario. Evitamos consumir OpenRouter
        # y arrancar Docker en ese caso.
        if not last_user_message:
            return AgentResponse(
                text=(
                    "Hola. Puedo consultar Uyuni y elegir dinámicamente cómo "
                    "presentar los resultados con CopilotKit Generative UI."
                )
            )

        tool_decision = await self._decide_tool_and_arguments(
            last_user_message
        )

        print("Unified tool decision:", tool_decision)

        if tool_decision.get("should_call_tool") is True:
            return await self._execute_tool_decision_rich(
                original_user_message=last_user_message,
                tool_decision=tool_decision,
                frontend_tools=frontend_tools,
            )

        clarification = tool_decision.get("clarification")
        if isinstance(clarification, str) and clarification.strip():
            return AgentResponse(text=clarification.strip())

        # Si la primera llamada concluye que no hace falta Uyuni, la segunda
        # llamada responde como chatbot normal usando el historial completo.
        text = await self.llm_provider.generate_response(chat_messages)
        return AgentResponse(text=text)

    async def _get_available_tools(
        self,
    ) -> list[MCPToolDefinition]:
        """
        Devuelve el catálogo de tools de lectura y lo cachea durante la vida
        del proceso del backend.

        Esto evita repetir list_tools() y arrancar un contenedor MCP solo para
        redescubrir el mismo catálogo en cada mensaje.
        """

        if self._cached_uyuni_tools is None:
            tools = await self.uyuni_client.list_tools()
            self._cached_uyuni_tools = list(tools)

        return self._cached_uyuni_tools

    async def _decide_tool_and_arguments(
        self,
        user_message: str,
    ) -> dict[str, Any]:
        """
        Unifica en UNA llamada LLM:
        - decidir si la petición necesita Uyuni;
        - elegir una tool real del catálogo;
        - construir sus argumentos.

        El backend sigue validando que la tool exista realmente y que no se
        envíen nombres de argumentos inexistentes.
        """

        available_tools = await self._get_available_tools()

        if not available_tools:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "El MCP de Uyuni no ha anunciado ninguna herramienta "
                    "de lectura disponible."
                ),
            }

        tool_catalog = self._build_tool_decision_catalog(available_tools)

        decision_messages = [
            ChatMessage(
                role="system",
                content=f"""
Eres el router y selector de herramientas de lectura del servidor MCP de Uyuni.

Debes resolver en UNA sola decisión estas tres tareas:
1. Decidir si la petición necesita consultar datos reales de Uyuni.
2. Si los necesita, elegir exactamente UNA tool del catálogo real.
3. Construir los argumentos de esa tool respetando su input_schema.

CATÁLOGO REAL DE HERRAMIENTAS:
{tool_catalog}

Cuándo usar Uyuni:
- sistemas, servidores o hosts registrados;
- detalles o búsqueda de sistemas por nombre/IP;
- actualizaciones, parches, erratas o CVE;
- reinicios pendientes;
- eventos o acciones programadas;
- activation keys;
- grupos de sistemas;
- o si el usuario pide explícitamente una tool disponible del MCP de Uyuni.

No uses Uyuni para conversación general, explicaciones teóricas ni preguntas
que no necesiten datos reales del servidor.

Reglas obligatorias:
- Devuelve exclusivamente JSON válido, sin Markdown ni explicaciones.
- Solo puedes seleccionar una tool cuyo nombre aparezca exactamente en el catálogo.
- No inventes tools ni nombres de argumentos.
- Usa exclusivamente argumentos definidos en input_schema.
- Respeta los tipos del input_schema.
- Omite argumentos opcionales que el usuario no haya pedido.
- Si falta un argumento obligatorio que no puedas deducir con seguridad,
  devuelve should_call_tool=false y una pregunta breve en clarification.
- Si no hace falta Uyuni, devuelve should_call_tool=false sin inventar una tool.

Formato cuando hay que ejecutar una tool:
{{
  "should_call_tool": true,
  "server": "mcp_uyuni",
  "tool": "nombre_exacto",
  "arguments": {{}}
}}

Formato cuando no hace falta Uyuni:
{{
  "should_call_tool": false,
  "server": null,
  "tool": null,
  "arguments": {{}}
}}

Formato cuando falta un dato obligatorio:
{{
  "should_call_tool": false,
  "server": null,
  "tool": null,
  "arguments": {{}},
  "clarification": "pregunta breve"
}}
""".strip(),
            ),
            ChatMessage(role="user", content=user_message),
        ]

        raw_response = await self.llm_provider.generate_response(
            decision_messages
        )
        print("LLM unified decision raw response:", raw_response)

        parsed = self._parse_json_from_text(raw_response)

        if parsed is None:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "reason": "invalid_json_from_unified_tool_decision",
                "raw_response": raw_response,
            }

        decision = self._normalize_tool_decision(parsed)
        decision = self._validate_tool_decision(
            decision,
            available_tools,
        )

        if decision.get("should_call_tool") is not True:
            return decision

        selected_tool_name = decision.get("tool")
        selected_tool = next(
            (
                tool
                for tool in available_tools
                if tool.name == selected_tool_name
            ),
            None,
        )

        if selected_tool is None:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "No he podido seleccionar una herramienta válida de Uyuni."
                ),
            }

        return self._validate_generated_arguments(
            decision=decision,
            selected_tool=selected_tool,
        )

    def _validate_generated_arguments(
        self,
        decision: dict[str, Any],
        selected_tool: MCPToolDefinition,
    ) -> dict[str, Any]:
        """
        Validación determinista mínima de los argumentos generados por el LLM.

        No sustituye la validación del propio MCP, pero evita ejecutar una tool
        si el modelo inventa nombres de parámetros o omite uno obligatorio.
        """

        arguments = decision.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}

        input_schema = selected_tool.input_schema or {}
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])

        if not isinstance(properties, dict):
            properties = {}

        if not isinstance(required, list):
            required = []

        unknown_arguments = [
            key for key in arguments
            if key not in properties
        ]

        if unknown_arguments:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "El modelo ha generado argumentos que no existen en el "
                    f"schema de {selected_tool.name}: "
                    f"{', '.join(sorted(unknown_arguments))}."
                ),
            }

        missing_required = [
            key for key in required
            if key not in arguments
        ]

        if missing_required:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "Falta información obligatoria para ejecutar "
                    f"{selected_tool.name}: "
                    f"{', '.join(missing_required)}."
                ),
            }

        return {
            "should_call_tool": True,
            "server": "mcp_uyuni",
            "tool": selected_tool.name,
            "arguments": arguments,
        }

    async def _execute_tool_decision(
        self,
        original_user_message: str,
        tool_decision: dict[str, Any],
    ) -> str:
        """Compatibilidad con el contrato textual anterior."""

        response = await self._execute_tool_decision_rich(
            original_user_message=original_user_message,
            tool_decision=tool_decision,
            frontend_tools=None,
        )
        return response.text

    async def _execute_tool_decision_rich(
        self,
        original_user_message: str,
        tool_decision: dict[str, Any],
        frontend_tools: Sequence[Any] | None = None,
    ) -> AgentResponse:
        """Ejecuta la tool y prepara texto + visuales sin alterar los datos MCP."""

        server = tool_decision.get("server")
        tool = tool_decision.get("tool")
        arguments = tool_decision.get("arguments", {})

        if server != "mcp_uyuni":
            return AgentResponse(
                text=(
                    "El modelo ha solicitado una herramienta de un servidor MCP "
                    f"no soportado todavía: {server}"
                )
            )

        available_tools = {
            available_tool.name: available_tool
            for available_tool in await self._get_available_tools()
        }

        if not isinstance(tool, str) or tool not in available_tools:
            return AgentResponse(
                text=(
                    "El modelo ha solicitado una herramienta que no está disponible "
                    f"entre las tools de lectura de Uyuni: {tool}"
                )
            )

        if not isinstance(arguments, dict):
            arguments = {}

        print(f"Ejecutando MCP Uyuni tool={tool} arguments={arguments}")

        call_tool_with_data = getattr(self.uyuni_client, "call_tool_with_data", None)
        if callable(call_tool_with_data):
            tool_result = await call_tool_with_data(tool, arguments)
        else:
            # Compatibilidad defensiva con dobles de prueba o clientes antiguos
            # que solo implementen el contrato textual ``call_tool``.
            legacy_text = await self.uyuni_client.call_tool(tool, arguments)
            tool_result = MCPToolResult(text=legacy_text)

        print("MCP Uyuni raw result:", tool_result.text)

        presentation = await self._generate_final_answer_and_genui(
            original_user_message=original_user_message,
            tool_name=tool,
            tool_result=tool_result.text,
            structured_data=tool_result.structured_data,
            frontend_tools=frontend_tools,
        )

        return presentation

    async def _generate_final_answer_and_genui(
        self,
        original_user_message: str,
        tool_name: str,
        tool_result: str,
        structured_data: Any,
        frontend_tools: Sequence[Any] | None,
    ) -> AgentResponse:
        """
        Genera en UNA sola inferencia la respuesta textual y la presentación
        CopilotKit Generative UI.

        A diferencia del experimento AG-UI anterior, aquí NO existe un mapa
        ``tool MCP -> tipo de visualización``. Los componentes React registrados
        por ``useComponent`` llegan en ``RunAgentInput.tools`` y el propio LLM
        decide cuál (o cuáles) usar en función de:
        - la petición concreta del usuario;
        - la forma y semántica de los datos reales devueltos por Uyuni;
        - las descripciones y schemas de los componentes disponibles.

        Así, ``list_systems`` puede acabar en tabla, tarjetas, gráfico, o sin
        componente, y una petición explícita de barras/pastel/líneas tiene
        prioridad siempre que pueda representarse sin inventar datos.
        """

        ui_tools = self._get_genui_frontend_tools(frontend_tools)

        # Mantiene compatibilidad con cualquier cliente AG-UI que no registre
        # componentes CopilotKit. En ese caso solo generamos texto.
        if not ui_tools:
            text = await self._generate_final_answer_from_tool_result(
                original_user_message=original_user_message,
                tool_name=tool_name,
                tool_result=tool_result,
            )
            return AgentResponse(text=text)

        ui_catalog = self._build_frontend_ui_catalog(ui_tools)
        source_data = structured_data if structured_data is not None else tool_result

        if not isinstance(source_data, str):
            try:
                source_text = json.dumps(
                    source_data,
                    ensure_ascii=False,
                    default=str,
                )
            except (TypeError, ValueError):
                source_text = str(source_data)
        else:
            source_text = source_data

        # Evita enviar accidentalmente resultados gigantes al modelo. Las tools
        # actuales de lectura ya vienen paginadas, pero dejamos un límite
        # defensivo para futuros MCPs.
        source_text = source_text[:50000]

        presentation_messages = [
            ChatMessage(
                role="system",
                content=f"""
Eres el asistente de TFG MCP UI y, además, el diseñador de la presentación
Generative UI de CopilotKit.

El backend YA ha ejecutado una herramienta real del MCP de Uyuni. Tu trabajo es:
1. Redactar una respuesta textual breve y fiel al resultado.
2. Decidir de forma DINÁMICA si conviene mostrar uno o varios componentes de UI.
3. Si usas UI, elegir exclusivamente entre los componentes React que el
   frontend ha registrado y rellenar sus argumentos con datos del resultado.

COMPONENTES GENUI DISPONIBLES EN ESTE TURNO:
{ui_catalog}

REGLAS DE DECISIÓN DE UI:
- NO existe ninguna correspondencia fija entre una tool MCP y un componente.
- Decide en cada petición qué representación comunica mejor la información.
- Si el usuario pide explícitamente un tipo de visualización (por ejemplo
  barras, líneas, pastel, tabla, tarjetas o timeline), intenta usar ese tipo.
- Si no pide un tipo concreto, elige libremente según la semántica y la forma
  de los datos. Puedes decidir no mostrar ningún componente si el texto basta.
- Una tabla suele ser útil para comparar registros con varios campos, pero NO
  es obligatoria por devolver una lista.
- Barras son útiles para comparar magnitudes entre categorías.
- Líneas son útiles cuando existe un orden temporal o secuencial real.
- Pastel/donut es útil para proporciones de un total.
- Tarjetas métricas son útiles para resúmenes con pocos indicadores.
- Detalle es útil para una entidad con atributos heterogéneos.
- Timeline es útil para eventos con orden o fecha.
- Estas son heurísticas, NO reglas deterministas.

REGLAS DE FIDELIDAD:
- No inventes sistemas, fechas, estados, cantidades ni métricas.
- Todo valor presentado debe proceder del resultado real o ser una derivación
  aritmética trivial y comprobable (por ejemplo contar elementos o agrupar
  categorías existentes).
- No uses IDs como si fueran magnitudes cuantitativas salvo que el usuario lo
  pida explícitamente.
- Si una visualización solicitada no tiene una métrica válida, explícalo
  brevemente y usa una alternativa fiel en vez de inventar datos.
- Respeta exactamente el JSON Schema de cada componente.
- No inventes nombres de componentes.
- Como máximo usa 2 componentes por respuesta para no saturar el chat.
- Responde en el mismo idioma que el usuario.

Devuelve EXCLUSIVAMENTE JSON válido con esta forma:
{{
  "answer": "respuesta textual para el usuario",
  "ui_calls": [
    {{
      "name": "nombre_exacto_del_componente",
      "arguments": {{}}
    }}
  ]
}}

Si no hace falta UI devuelve "ui_calls": [].
""".strip(),
            ),
            ChatMessage(
                role="user",
                content=f"""
Petición original:
{original_user_message}

Tool MCP ejecutada:
{tool_name}

Resultado real de Uyuni:
{source_text}

Genera la respuesta y decide la presentación CopilotKit GenUI.
""".strip(),
            ),
        ]

        raw_response = await self.llm_provider.generate_response(
            presentation_messages
        )
        print("LLM GenUI presentation raw response:", raw_response)

        parsed = self._parse_json_from_text(raw_response)

        if parsed is None:
            # Fallback conservador: nunca rompemos una consulta MCP porque el
            # modelo haya formateado mal únicamente la parte de presentación.
            print("GenUI JSON inválido; usando fallback textual")
            text = await self._generate_final_answer_from_tool_result(
                original_user_message=original_user_message,
                tool_name=tool_name,
                tool_result=tool_result,
            )
            return AgentResponse(text=text)

        answer = parsed.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            answer = "He obtenido los datos solicitados de Uyuni."

        valid_calls = self._normalize_genui_calls(
            parsed.get("ui_calls"),
            ui_tools,
        )

        print(
            "Validated CopilotKit GenUI calls:",
            [
                {"name": call.name, "arguments": call.arguments}
                for call in valid_calls
            ],
        )

        return AgentResponse(
            text=answer.strip(),
            ui_calls=valid_calls,
        )

    def _get_genui_frontend_tools(
        self,
        frontend_tools: Sequence[Any] | None,
    ) -> list[Any]:
        """Filtra únicamente componentes display-only registrados por CopilotKit."""

        if not frontend_tools:
            return []

        result: list[Any] = []
        for tool in frontend_tools:
            name = getattr(tool, "name", None)
            if isinstance(tool, dict):
                name = tool.get("name", name)

            # Todos los componentes de esta variante usan el prefijo render_.
            # Así una futura frontend tool operativa no puede ser llamada por
            # accidente desde la fase dedicada exclusivamente a presentación.
            if isinstance(name, str) and name.startswith("render_"):
                result.append(tool)

        return result

    def _build_frontend_ui_catalog(self, tools: Sequence[Any]) -> str:
        """Serializa nombre, descripción y schema de los componentes GenUI."""

        catalog: list[dict[str, Any]] = []

        for tool in tools:
            name = getattr(tool, "name", None)
            description = getattr(tool, "description", "")
            parameters = getattr(tool, "parameters", None)

            if isinstance(tool, dict):
                name = tool.get("name", name)
                description = tool.get("description", description)
                parameters = tool.get("parameters", parameters)

            if not isinstance(name, str):
                continue

            catalog.append(
                {
                    "name": name,
                    "description": str(description or ""),
                    "parameters": parameters or {},
                }
            )

        return json.dumps(
            catalog,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )

    def _normalize_genui_calls(
        self,
        raw_calls: Any,
        available_tools: Sequence[Any],
    ) -> list[UIComponentCall]:
        """
        Valida de forma defensiva las decisiones de presentación del LLM.

        La selección sigue siendo del modelo; esta función solo impide nombres
        inventados, argumentos desconocidos y payloads absurdamente grandes.
        """

        if not isinstance(raw_calls, list):
            return []

        tool_schemas: dict[str, dict[str, Any]] = {}
        for tool in available_tools:
            name = getattr(tool, "name", None)
            parameters = getattr(tool, "parameters", None)
            if isinstance(tool, dict):
                name = tool.get("name", name)
                parameters = tool.get("parameters", parameters)

            if isinstance(name, str):
                tool_schemas[name] = parameters if isinstance(parameters, dict) else {}

        valid_calls: list[UIComponentCall] = []

        for candidate in raw_calls[:2]:
            if not isinstance(candidate, dict):
                continue

            name = candidate.get("name")
            arguments = candidate.get("arguments", {})

            if not isinstance(name, str) or name not in tool_schemas:
                continue
            if not isinstance(arguments, dict):
                continue

            normalized_arguments = self._validate_ui_call_arguments(
                arguments,
                tool_schemas[name],
            )
            if normalized_arguments is None:
                continue

            try:
                serialized_size = len(
                    json.dumps(
                        normalized_arguments,
                        ensure_ascii=False,
                        default=str,
                    )
                )
            except (TypeError, ValueError):
                continue

            if serialized_size > 60000:
                continue

            valid_calls.append(
                UIComponentCall(
                    name=name,
                    arguments=normalized_arguments,
                )
            )

        return valid_calls

    def _validate_ui_call_arguments(
        self,
        arguments: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Valida y sanea el subconjunto de JSON Schema usado por los componentes.

        CopilotKit registra los schemas de ``useComponent`` como tools AG-UI.
        El LLM sigue decidiendo QUÉ componente usa y CON QUÉ datos, pero antes
        de emitir el tool call comprobamos tipos, campos obligatorios, arrays y
        enums para que una salida JSON defectuosa no pueda romper el renderer.
        """

        valid, cleaned = self._sanitize_value_against_schema(arguments, schema)
        if not valid or not isinstance(cleaned, dict):
            return None
        return cleaned

    def _sanitize_value_against_schema(
        self,
        value: Any,
        schema: Any,
    ) -> tuple[bool, Any]:
        """Validador defensivo pequeño para el JSON Schema de GenUI."""

        if not isinstance(schema, dict) or not schema:
            return True, value

        # Zod puede expresar uniones mediante anyOf/oneOf. Aceptamos la
        # primera rama cuyo tipo/estructura cuadre con el valor generado.
        alternatives = schema.get("anyOf") or schema.get("oneOf")
        if isinstance(alternatives, list):
            for alternative in alternatives:
                valid, cleaned = self._sanitize_value_against_schema(
                    value, alternative
                )
                if valid:
                    return True, cleaned
            return False, None

        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and value not in enum_values:
            return False, None

        expected_type = schema.get("type")
        if isinstance(expected_type, list):
            for type_name in expected_type:
                branch = dict(schema)
                branch["type"] = type_name
                valid, cleaned = self._sanitize_value_against_schema(value, branch)
                if valid:
                    return True, cleaned
            return False, None

        if expected_type == "object" or (
            expected_type is None
            and ("properties" in schema or "additionalProperties" in schema)
        ):
            if not isinstance(value, dict):
                return False, None

            properties = schema.get("properties", {})
            required = schema.get("required", [])
            if not isinstance(properties, dict):
                properties = {}

            # Para objetos con propiedades declaradas tratamos el payload como
            # cerrado aunque el conversor no haya emitido additionalProperties.
            # Los z.record de las filas sí anuncian additionalProperties y se
            # conservan como mapas dinámicos.
            additional = schema.get(
                "additionalProperties",
                False if properties else True,
            )
            if not isinstance(required, list):
                required = []

            if any(key not in value for key in required if isinstance(key, str)):
                return False, None

            cleaned_object: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    continue

                if key in properties:
                    valid, cleaned_item = self._sanitize_value_against_schema(
                        item, properties[key]
                    )
                    if not valid:
                        return False, None
                    cleaned_object[key] = cleaned_item
                    continue

                if additional is False:
                    # Campo alucinado: se descarta sin invalidar todo el call.
                    continue

                if isinstance(additional, dict):
                    valid, cleaned_item = self._sanitize_value_against_schema(
                        item, additional
                    )
                    if not valid:
                        return False, None
                    cleaned_object[key] = cleaned_item
                else:
                    cleaned_object[key] = item

            # Un campo required puede haber sido filtrado por un schema extraño;
            # comprobación final por seguridad.
            if any(
                key not in cleaned_object
                for key in required
                if isinstance(key, str)
            ):
                return False, None

            return True, cleaned_object

        if expected_type == "array":
            if not isinstance(value, list):
                return False, None

            min_items = schema.get("minItems")
            max_items = schema.get("maxItems")
            if isinstance(min_items, int) and len(value) < min_items:
                return False, None

            items = schema.get("items", {})
            source_items = value
            if isinstance(max_items, int) and max_items >= 0:
                source_items = source_items[:max_items]

            cleaned_items: list[Any] = []
            for item in source_items:
                valid, cleaned_item = self._sanitize_value_against_schema(
                    item, items
                )
                if not valid:
                    return False, None
                cleaned_items.append(cleaned_item)

            return True, cleaned_items

        if expected_type == "string":
            return (isinstance(value, str), value if isinstance(value, str) else None)

        if expected_type == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
            return valid, value if valid else None

        if expected_type == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
            return valid, value if valid else None

        if expected_type == "boolean":
            return (isinstance(value, bool), value if isinstance(value, bool) else None)

        if expected_type == "null":
            return (value is None, None)

        # Keywords no estructurales que no necesitamos interpretar no deben
        # convertir una respuesta válida en un fallo de presentación.
        return True, value

    async def _generate_final_answer_from_tool_result(
        self,
        original_user_message: str,
        tool_name: str,
        tool_result: str,
    ) -> str:
        """
        Pide al LLM que redacte la respuesta final usando el resultado real
        devuelto por la herramienta MCP.
        """

        final_answer_messages = [
            ChatMessage(
                role="system",
                content="""
Eres el asistente conversacional de TFG MCP UI.

Has recibido el resultado real de una herramienta MCP ya ejecutada por el backend.

Reglas:
- No inventes datos.
- Usa únicamente el resultado de la herramienta.
- No digas que no tienes acceso al sistema, porque el backend ya ha consultado la herramienta.
- No menciones detalles internos innecesarios.
- Responde en el mismo idioma que el usuario.
- Sé claro y breve.
- Si el resultado contiene JSON, explícalo de forma legible.
""".strip(),
            ),
            ChatMessage(
                role="user",
                content=f"""
Mensaje original del usuario:
{original_user_message}

Herramienta ejecutada:
{tool_name}

Resultado real de la herramienta:
{tool_result}

Redacta la respuesta final para el usuario.
""".strip(),
            ),
        ]

        return await self.llm_provider.generate_response(final_answer_messages)

    def _build_tool_decision_catalog(
        self,
        tools: Sequence[MCPToolDefinition],
    ) -> str:
        """
        Catálogo completo para la decisión unificada.

        Incluye nombre, descripción e input_schema porque el LLM debe elegir la
        tool y generar sus argumentos en la misma inferencia.
        """

        catalog = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema or {},
            }
            for tool in tools
        ]

        return json.dumps(
            catalog,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _validate_tool_decision(
        self,
        decision: dict[str, Any],
        available_tools: Sequence[MCPToolDefinition],
    ) -> dict[str, Any]:
        """
        Nunca confía ciegamente en el nombre de tool escrito por el LLM.
        Solo permite ejecutar nombres descubiertos realmente por el MCP.
        """

        if decision.get("should_call_tool") is not True:
            return decision

        valid_tool_names = {tool.name for tool in available_tools}

        if decision.get("server") != "mcp_uyuni":
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "La selección de herramienta no pertenece al servidor MCP de Uyuni."
                ),
            }

        selected_tool = decision.get("tool")

        if not isinstance(selected_tool, str) or selected_tool not in valid_tool_names:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "No he podido seleccionar de forma segura una herramienta de lectura válida de Uyuni."
                ),
            }

        return decision

    def _parse_json_from_text(self, text: str) -> dict[str, Any] | None:
        """
        Intenta extraer JSON aunque el modelo lo devuelva rodeado de texto
        o bloques Markdown.
        """

        clean_text = text.strip()

        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```json\s*", "", clean_text)
            clean_text = re.sub(r"^```\s*", "", clean_text)
            clean_text = re.sub(r"\s*```$", "", clean_text)

        try:
            return json.loads(clean_text)
        except json.JSONDecodeError:
            pass

        first_brace = clean_text.find("{")
        last_brace = clean_text.rfind("}")

        if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
            return None

        json_candidate = clean_text[first_brace : last_brace + 1]

        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            return None

    def _normalize_tool_decision(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Normaliza la decisión del LLM para que el resto del backend trabaje
        siempre con una estructura conocida.
        """

        should_call_tool = bool(data.get("should_call_tool", False))

        server = data.get("server")
        tool = data.get("tool")
        arguments = data.get("arguments", {})
        clarification = data.get("clarification")

        if not isinstance(arguments, dict):
            arguments = {}

        normalized = {
            "should_call_tool": should_call_tool,
            "server": server,
            "tool": tool,
            "arguments": arguments,
        }

        if isinstance(clarification, str):
            normalized["clarification"] = clarification

        return normalized

    def _convert_agui_message_to_chat_message(self, message: Any) -> ChatMessage:
        """
        Convierte un mensaje recibido desde AG-UI al formato interno ChatMessage.
        """

        role = getattr(message, "role", None)
        content = getattr(message, "content", None)

        if isinstance(message, dict):
            role = message.get("role", role)
            content = message.get("content", content)

        if role is None:
            role = "user"

        if content is None:
            content = ""

        if not isinstance(content, str):
            content = str(content)

        return ChatMessage(
            role=str(role),
            content=content,
        )

    def _get_last_user_message(self, messages: Sequence[ChatMessage]) -> str:
        """
        Obtiene el último mensaje enviado por el usuario.
        """

        for message in reversed(messages):
            if message.role.lower().strip() == "user":
                return message.content.strip()

        return ""