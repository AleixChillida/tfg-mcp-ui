import { useState } from 'react'
import './App.css'

function App() {
  const [message, setMessage] = useState('Sin comprobar')
  const [loading, setLoading] = useState(false)

  const checkBackend = async () => {
    try {
      setLoading(true)

      const response = await fetch('http://127.0.0.1:8000/')
      const data = await response.json()

      setMessage(data.message)
    } catch (error) {
      setMessage('Error conectando con el backend')
      console.error(error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: '2rem', fontFamily: 'Arial, sans-serif' }}>
      <h1>TFG MCP UI</h1>
      <p>Prueba de conexión frontend-backend</p>

      <button onClick={checkBackend} disabled={loading}>
        {loading ? 'Comprobando...' : 'Comprobar backend'}
      </button>

      <p style={{ marginTop: '1rem' }}>
        <strong>Respuesta del backend:</strong> {message}
      </p>
    </div>
  )
}

export default App