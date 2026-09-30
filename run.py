"""Punto de entrada para ejecutar la aplicación DDN Travel en modo desarrollo."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)