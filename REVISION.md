# Revisión del flujo de ecommerce y descuento por nómina

## Problemas encontrados en el proyecto recibido

- El carrito tenía modelos y vistas, pero no existía su migración; la base incluida no tenía tablas de carrito.
- El botón **Continuar compra** estaba deshabilitado.
- El enlace **Carrito** del menú apuntaba a `#`.
- `pedidos/views.py` importaba `Pedido` y `PedidoItem`, pero `pedidos/models.py` estaba vacío.
- Las vistas de pedidos hacían referencia a `combo` y `nombre_mostrar`, campos que no existen en el carrito actual.
- `pedidos` no tenía URLs conectadas al proyecto ni plantilla de confirmación.
- La solicitud de nómina tomaba el total del carrito, pero no quedaba vinculada a un pedido ni conservaba una copia de los productos solicitados.
- La notificación al fondo estaba solamente comentada; no se enviaba nada.
- El fondo no tenía un portal restringido para validar vinculación, cupo y decisión.
- Las plantillas `mis_solicitudes.html`, `detalle_solicitud.html` y `seguridad/login.html` estaban vacías.
- Las migraciones históricas de `fondos` no coincidían con el modelo Python actual.

## Flujo implementado

1. El usuario agrega una presentación de producto al carrito.
2. En el carrito pulsa **Continuar compra**.
3. Si no inició sesión, Django solicita ingreso y luego recupera/fusiona el carrito de sesión.
4. En checkout ingresa dirección, ciudad y selecciona el medio de pago.
5. Se crea un `Pedido` y `PedidoItem` con una copia de productos, cantidades y precios.
6. Si selecciona **Descuento por nómina**, pasa al formulario de solicitud asociado al pedido.
7. La plataforma envía una notificación por correo al fondo y a sus usuarios gestores.
8. Un gestor autorizado entra a **Gestionar nómina**, valida si la persona pertenece a la entidad, reporta cupo y aprueba, aprueba parcialmente o rechaza.
9. La decisión actualiza automáticamente el estado del pedido y notifica al usuario por correo.
10. El usuario puede consultar **Mis pedidos** y **Mis solicitudes de nómina**.

## Configuración necesaria

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

En el administrador de Django:

1. Crear/editar el fondo de empleados.
2. Registrar un correo del fondo.
3. Asignar uno o más usuarios en el campo **gestores**.

En desarrollo, los correos se imprimen en consola. Para producción configure variables de entorno como `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` y `DEFAULT_FROM_EMAIL`.

## Pendiente para producción

- Integrar la pasarela de pago electrónico real.
- Definir cifrado/retención para documento, teléfono y otros datos personales.
- Agregar auditoría de cambios de las respuestas del fondo.
- Definir qué debe ocurrir comercialmente cuando la aprobación sea parcial (por ejemplo, permitir ajustar el pedido al cupo aprobado).
- Reemplazar SQLite por PostgreSQL y mover `SECRET_KEY`, credenciales y configuración sensible a variables de entorno.

---

# Revisión 2 (2026-10-13): verificación del fondo y escalabilidad

## Errores corregidos

| Problema | Impacto | Solución |
|---|---|---|
| `notificar_fondo_nueva_solicitud(request, solicitud)` con firma de 1 argumento | **Error 500 al enviar toda solicitud de nómina** | Firma corregida; envío al confirmar la transacción |
| Faltaba `apps/__init__.py` | `manage.py test` no encontraba ninguna prueba | Agregado |
| `python-dotenv` no estaba en `requirements.txt` | Instalación limpia fallaba | Agregado |
| `SecurityMiddleware` al final | Cabeceras de seguridad mal aplicadas | Movido al inicio |
| Stock de combos se validaba pero no se descontaba | Sobreventa | Descuento atómico (`F()` + condición `stock >= cantidad`) |
| Resumen del checkout vacío para combos | UX | Usa `nombre_mostrar` / `detalle_mostrar` |
| Categorías del menú con IDs fijos (1..5) | Se rompe al cambiar el catálogo | Menú dinámico vía context processor |
| No existía registro de usuarios | Nadie nuevo podía comprar | `/cuenta/registro/` |
| Gestor podía cambiar una decisión ya tomada / admin editaba estado sin efectos | Inconsistencias pedido–solicitud | Decisión única vía `services.aplicar_decision`; admin en solo lectura |

## Verificación del fondo: ¿es empleado?, ¿total, parcial o denegada?

Cada fondo (admin → Fondos de empleados) elige su **modo de verificación**:

| Modo | Cómo verifica | Ideal para |
|---|---|---|
| `MANUAL` | El gestor revisa en *Gestionar nómina* | Fondos pequeños / arranque |
| `PADRON` | Busca el documento en el padrón que el fondo carga por CSV | La mayoría de fondos |
| `API` | Consulta en línea el servicio web del fondo | Fondos con sistemas propios |

Con **decisión automática** activa y verificación concluyente, la plataforma responde al instante:

- No está en el padrón / inactivo / API dice `vinculado: false` / cupo 0 → **Denegada**
- Cupo ≥ valor del pedido → **Aprobación completa**
- 0 < cupo < valor → **Aprobación parcial** por el cupo disponible

Si la verificación no es concluyente (modo manual, API caída), queda **pendiente** para el gestor,
con la sugerencia de vinculación y cupo ya precargada.

El cupo aprobado se **descuenta del padrón** (con bloqueo de fila, seguro ante compras simultáneas)
y se **devuelve** si el pedido se cancela. Toda verificación y decisión queda en `HistorialSolicitud`.

### Aprobación parcial o rechazo
El comprador ve en su pedido el valor cubierto por nómina y el saldo, y puede:
**pagar el saldo con otro medio** (el pedido pasa a *Pendiente de pago* por el saldo) o **cancelar**
(se devuelve stock de combos y cupo del padrón).

### Cargar el padrón
- Portal: *Gestionar nómina* → botón **Padrón <fondo>** (solo gestores de ese fondo).
- Consola: `python manage.py importar_padron "FONDO COLSUBSIDIO" docs/padron_ejemplo.csv [--desactivar-ausentes]`
- Formato: ver `docs/padron_ejemplo.csv` (`;` o `,`, montos `1.500.000` o `1500000`).

### Contrato del modo API
`POST <api_url>` con `Authorization: Bearer <token>` (el token se lee de la variable de entorno
cuyo **nombre** se configura en `api_token_env`; nunca se guarda en BD):

```json
{"documento": "1020304050", "nombre": "...", "empresa": "...", "numero_afiliado": "",
 "valor_solicitado": "100000.00", "referencia_pedido": "PED-20261013-AB12CD34"}
```
Respuesta esperada: `{"vinculado": true, "cupo_disponible": 80000, "referencia": "X-1", "mensaje": "..."}`

Para agregar otro tipo de integración (SOAP, SFTP…): subclase de `Verificador` en
`apps/fondos/verificacion.py` decorada con `@registrar("MODO")`.

## Arquitectura para escalar

- **Vistas delgadas, lógica en servicios** (`apps/pedidos/services.py`, `apps/fondos/services.py`):
  la misma lógica sirve para una API REST o app móvil futura.
- **Verificación desacoplada** (`procesar_verificacion(solicitud_id)`): recibe un ID y corre fuera
  de transacciones, lista para moverse a una cola (Celery/RQ) cuando haya volumen.
- **PostgreSQL** por variables de entorno (`DB_NAME`, …) — necesario en producción para los
  bloqueos de fila. Ver `.env.example`.
- Importación de padrón con `bulk_create`/`bulk_update` (miles de afiliados por carga).
- Índices en `Pedido(usuario, created_at)`, `Pedido(estado)`, `Solicitud(fondo, estado)`; listado
  del gestor paginado con filtros.
- Endurecimiento automático con `DEBUG=0` (cookies seguras, HSTS, SSL, exige `DJANGO_SECRET_KEY`).

## Pruebas
```bash
python manage.py test
```
27 pruebas: reglas de decisión, flujo manual, padrón (total/parcial/denegado, consumo de cupo,
cancelación), API (aprobación, rechazo, caída), importación CSV, permisos entre fondos,
stock de combos, registro y render de pantallas.

## Siguientes pasos recomendados
1. Integrar la pasarela de pagos (Wompi / PayU / Mercado Pago) en `apps/pagos` para el pago electrónico y el saldo.
2. Mover `procesar_verificacion` y los correos a Celery + Redis cuando el volumen lo requiera.
3. Webhook firmado (HMAC) para fondos que respondan de forma asíncrona.
4. Cifrado de `documento`/`telefono` en reposo y política de retención (Ley 1581 de 2012, habeas data) + autorización de tratamiento de datos en el formulario de nómina.
5. Reporte mensual de descuentos aprobados por fondo (archivo para que el fondo aplique el descuento en nómina).
6. API REST (Django REST Framework) sobre los servicios existentes.
