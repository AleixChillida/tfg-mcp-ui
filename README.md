# TFG — UI generativa per a l’administració de sistemes Linux amb MCP

Aquest repositori conté les tres variants desenvolupades al TFG:

- `tfg-mcp-ui-ag-ui`
- `tfg-mcp-ui-copilotkit-genui`
- `tfg-mcp-ui-mcp-apps`

Cada variant té un `backend` i un `frontend`. El més senzill és executar **una variant cada vegada**, ja que per defecte utilitzen els mateixos ports.

## Requisits previs

Cal tenir instal·lat:

- Python 3.10 o superior
- Node.js i npm
- Docker
- Accés a l'entorn d'Uyuni
- Una clau d'OpenRouter si s'utilitza `LLM_PROVIDER=openrouter`

## 1. Configurar el backend

Entra a la carpeta `backend` de la variant que vulguis executar.

Per exemple:

```powershell
cd tfg-mcp-ui-ag-ui\backend
```

Copia el fitxer d'exemple:

```powershell
Copy-Item .env.example .env
```

Edita `.env` i configura la teva clau d'OpenRouter i la ruta/configuració necessària per connectar amb l'MCP d'Uyuni.

> `.env` és privat i està ignorat per Git. No s'ha de pujar al repositori.

## 2. Instal·lar i arrencar el backend

La primera vegada:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requeriments.txt
```

Arrencar el backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Normalment quedarà disponible a:

```text
http://127.0.0.1:8000
```

## 3. Configurar el frontend

Obre una altra terminal i entra a la carpeta `frontend` de la mateixa variant.

Per exemple:

```powershell
cd tfg-mcp-ui-ag-ui\frontend
```

Copia el fitxer d'exemple:

```powershell
Copy-Item .env.example .env
```

No cal modificar-lo si el backend s'executa amb les adreces i ports per defecte.

## 4. Instal·lar i arrencar el frontend

La primera vegada:

```powershell
npm install
```

Arrencar el frontend:

```powershell
npm run dev
```

Vite mostrarà a la terminal l'adreça del frontend, normalment:

```text
http://127.0.0.1:5173
```

## Execucions posteriors

Un cop creades les configuracions i instal·lades les dependències:

### Backend

```powershell
cd <variant>\backend
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

### Frontend

```powershell
cd <variant>\frontend
npm run dev
```

## Variants

Per executar una altra variant, només cal repetir els mateixos passos canviant `<variant>` per:

```text
tfg-mcp-ui-ag-ui
tfg-mcp-ui-copilotkit-genui
tfg-mcp-ui-mcp-apps
```
