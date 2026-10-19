# P7 - Verificacion de interfaz y gestion

## Implementado

- Los formularios de catalogo cubren destinos, paquetes, hoteles y tipos de habitacion, vuelos, transporte y actividades.
- Se incluyen controles de clientes, usuarios y reservas, panel de pagos/facturas e itinerarios.
- `base.html` no expone `window.DDN_DATA`; `static/js/api.js` se carga antes de `app.js`.
- Los formularios POST incluyen CSRF; las peticiones AJAX usan el token CSRF.
- La cotizacion de reservas y el total final se calculan en el servidor.
- El modal de catalogo enviaba AJAX al crear paquetes, vuelos, transportes y actividades, pero recibia redirecciones. Las rutas ahora responden JSON para crear y para reportar errores de validacion. Se agregaron pruebas en `tests/test_p7_ui.py`.

## Verificacion

- `py -3 -m compileall -q app tests`: correcto.
- `git diff --check`: correcto.
- No fue posible ejecutar `py -3 -m pytest tests -q`: el entorno no tiene pytest instalado.
- El recorrido visual en navegador sigue pendiente.
