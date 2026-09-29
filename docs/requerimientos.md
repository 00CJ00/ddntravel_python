# Requerimientos — Aplicación Inteligente para la Gestión de Agencia de Viajes Turísticos

> Fuente: documento de requerimientos del proyecto (PDF original conservado fuera del repo o en docs/).
> Este archivo es la referencia oficial de alcance. Los prompts de cada fase (P0–P9) citan los
> códigos relevantes a esa fase; ante cualquier duda de alcance, este documento es la fuente final.

## 1. Descripción general

| Elemento | Descripción |
|---|---|
| Nombre del proyecto | N/A |
| Tipo de sistema | Aplicación Web Inteligente |
| Área | Turismo y Gestión Empresarial |
| Objetivo | Automatizar la gestión de reservas, clientes, paquetes turísticos y servicios de una agencia de viajes |
| Usuarios principales | Administrador, Empleados y Clientes |
| Plataforma | Web Responsive |

## 2. Objetivo general

Diseñar e implementar una aplicación inteligente para la administración de agencias de viajes
turísticos, permitiendo optimizar reservas, paquetes turísticos, pagos y atención al cliente
mediante herramientas digitales automatizadas.

## 3. Alcance del proyecto

- Gestión de clientes
- Gestión de paquetes turísticos
- Gestión de reservas
- Gestión de hoteles
- Gestión de vuelos
- Gestión de pagos
- Dashboard estadístico
- Reportes administrativos
- Notificaciones automáticas
- Recomendaciones inteligentes

## 4. Requerimientos funcionales

| Código | Requerimiento |
|---|---|
| RF-01 | Gestión de usuarios y roles |
| RF-02 | Inicio y cierre de sesión |
| RF-03 | Gestión de clientes |
| RF-04 | Gestión de destinos turísticos |
| RF-05 | Gestión de paquetes turísticos |
| RF-06 | Gestión de reservas |
| RF-07 | Gestión de hoteles |
| RF-08 | Gestión de vuelos |
| RF-09 | Gestión de transporte turístico |
| RF-10 | Gestión de itinerarios |
| RF-11 | Gestión de pagos y facturación |
| RF-12 | Gestión de promociones |
| RF-13 | Sistema de notificaciones |
| RF-14 | Dashboard administrativo |
| RF-15 | Generación de reportes |
| RF-16 | Búsqueda avanzada |
| RF-17 | Gestión documental |
| RF-18 | Gestión de actividades turísticas |
| RF-19 | Auditoría del sistema |
| RF-20 | Recomendaciones inteligentes |

## 5. Requerimientos no funcionales

| Código | Requerimiento |
|---|---|
| RNF-01 | Seguridad mediante autenticación y roles |
| RNF-02 | Contraseñas cifradas |
| RNF-03 | Interfaz responsive |
| RNF-04 | Compatibilidad con navegadores modernos |
| RNF-05 | Soporte para múltiples usuarios |
| RNF-06 | Respaldo de información |
| RNF-07 | Escalabilidad del sistema |
| RNF-08 | Rendimiento eficiente |
| RNF-09 | Código mantenible y documentado |
| RNF-10 | Disponibilidad continua |

## 6. Roles del sistema

| Rol | Funciones principales |
|---|---|
| Administrador | Gestión general del sistema |
| Empleado | Gestión de reservas y clientes |
| Cliente | Consulta y reserva de paquetes |

## 7. Reglas de negocio

| Código | Regla |
|---|---|
| RN-01 | No se podrá reservar sin disponibilidad |
| RN-02 | Toda reserva deberá estar asociada a un cliente |
| RN-03 | Los pagos deberán registrarse antes de confirmar servicios |
| RN-04 | Solo administradores podrán eliminar información crítica |
| RN-05 | El sistema deberá registrar historial de cambios |

## 8. Tecnologías sugeridas

| Componente | Tecnologías |
|---|---|
| Frontend | HTML + JS + CSS |
| Backend | Node.js, Django o FastAPI |
| Base de datos | PostgreSQL, MySQL o MongoDB |
| Seguridad | JWT, HTTPS, Roles |
| Reportes | PDF y Excel |

> Nota de implementación: el proyecto real usa Flask (Python) en vez de Node.js/Django/FastAPI,
> y sesiones con CSRF en vez de JWT (ver AGENTS.md para la decisión y su justificación).

## 9. Funciones inteligentes

- Recomendación de paquetes turísticos
- Alertas automáticas
- Sugerencias de destinos
- Estadísticas automáticas
- Detección de clientes frecuentes
- Identificación de temporadas altas

## 10. Resultado esperado

Implementar una plataforma inteligente y moderna que permita automatizar la administración de
una agencia de viajes turísticos, mejorando la gestión operativa, comercial y la experiencia
del cliente.