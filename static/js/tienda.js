/* =========================================================
   TÍO CAMPO · Interacción de la tienda
   - Botón "Agregar" que se convierte en selector de cantidad.
   - Sincroniza contador y total del carrito sin recargar.
   - Carrito lateral (offcanvas) y avisos (toasts).
   Sin dependencias además de Bootstrap 5.
   ========================================================= */
(function () {
    "use strict";

    const config = document.getElementById("tc-config");
    if (!config) return;

    const URL_API = config.dataset.urlApi;          // /carrito/api/__tipo__/0/
    const URL_MINI = config.dataset.urlMini;        // /carrito/mini/
    const URL_CARRITO = config.dataset.urlCarrito;  // /carrito/
    const CSRF = config.dataset.csrf;
    const ESPERA_MS = 350;

    // Mismo formato que las plantillas: $5.200
    const numero = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });
    const moneda = { format: (valor) => "$" + numero.format(valor) };

    // Cantidades actuales en el carrito: {"p12": 2, "c3": 1}
    let cantidades = {};
    try {
        cantidades = JSON.parse(document.getElementById("tc-cantidades").textContent) || {};
    } catch (e) { cantidades = {}; }

    const pendientes = {};   // temporizadores por clave (debounce)

    /* ---------------- Utilidades ---------------- */

    function clave(add) {
        return add.dataset.tipo + add.dataset.id;
    }

    function aviso(texto, tipo, enlace) {
        const contenedor = document.getElementById("tc-toasts");
        if (!contenedor || !texto) return;
        const toast = document.createElement("div");
        toast.className = "tc-toast" + (tipo === "error" ? " tc-toast--error" : "");
        toast.setAttribute("role", "status");
        const icono = tipo === "error" ? "bi-exclamation-circle-fill" : "bi-check-circle-fill";
        toast.innerHTML = '<i class="bi ' + icono + '"></i><div></div>' +
            '<button type="button" aria-label="Cerrar"><i class="bi bi-x-lg"></i></button>';
        toast.querySelector("div").textContent = texto;
        if (enlace) {
            const a = document.createElement("a");
            a.href = enlace.href;
            a.textContent = " " + enlace.texto;
            toast.querySelector("div").appendChild(a);
        }
        toast.querySelector("button").addEventListener("click", () => toast.remove());
        contenedor.appendChild(toast);
        setTimeout(() => toast.remove(), 3500);
    }

    function actualizarResumen(cantidadTotal, total) {
        document.querySelectorAll("[data-cart-count]").forEach((el) => {
            el.textContent = cantidadTotal;
            el.dataset.vacio = cantidadTotal > 0 ? "0" : "1";
        });
        document.querySelectorAll("[data-cart-total]").forEach((el) => {
            el.textContent = moneda.format(Number(total));
        });
    }

    /* ---------------- Dibujo de un bloque "Agregar" ---------------- */

    function pintar(add) {
        const n = cantidades[clave(add)] || 0;
        const boton = add.querySelector(".tc-add__btn");
        const stepper = add.querySelector(".tc-stepper");
        if (!boton || !stepper) return;
        boton.hidden = n > 0;
        stepper.hidden = n === 0;
        const span = stepper.querySelector("[data-cantidad]");
        if (span) span.textContent = n;
        const mas = stepper.querySelector('[data-accion="mas"]');
        const maximo = Number(add.dataset.max || 99);
        if (mas) mas.disabled = n >= maximo;
    }

    function iniciar(add) {
        add.dataset.confirmada = cantidades[clave(add)] || 0;
        pintar(add);
    }

    function pintarClave(k) {
        document.querySelectorAll("[data-add]").forEach((add) => {
            if (clave(add) === k) pintar(add);
        });
    }

    /* ---------------- Comunicación con el servidor ---------------- */

    function enviar(k, add) {
        const tipo = add.dataset.tipo;
        const id = add.dataset.id;
        const url = URL_API.replace("__tipo__", tipo).replace(/\/0\/$/, "/" + id + "/");
        const cuerpo = new URLSearchParams({ cantidad: String(cantidades[k] || 0) });
        const anterior = add.dataset.confirmada ? Number(add.dataset.confirmada) : 0;

        return fetch(url, {
            method: "POST",
            headers: {
                "X-CSRFToken": CSRF,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            credentials: "same-origin",
            body: cuerpo,
        })
            .then((r) => r.json().then((datos) => ({ ok: r.ok, datos })))
            .then(({ ok, datos }) => {
                if (!ok || !datos.ok) throw new Error(datos.mensaje || "No se pudo actualizar el carrito.");
                cantidades[k] = datos.cantidad;
                document.querySelectorAll("[data-add]").forEach((el) => {
                    if (clave(el) === k) el.dataset.confirmada = datos.cantidad;
                });
                pintarClave(k);
                actualizarResumen(datos.cantidad_carrito, datos.total);
                if (datos.mensaje) aviso(datos.mensaje, "error");
                else if (anterior === 0 && datos.cantidad > 0) {
                    aviso((add.dataset.nombre || "Producto") + " agregado.", "ok",
                        { href: URL_CARRITO, texto: "Ver carrito" });
                }
                refrescarMini();
            })
            .catch((error) => {
                cantidades[k] = anterior;
                pintarClave(k);
                aviso(error.message || "Revisa tu conexión e inténtalo de nuevo.", "error");
            });
    }

    function cambiar(add, nuevaCantidad) {
        const k = clave(add);
        const maximo = Number(add.dataset.max || 99);
        cantidades[k] = Math.max(0, Math.min(nuevaCantidad, maximo));
        pintarClave(k);                       // respuesta inmediata en pantalla
        clearTimeout(pendientes[k]);
        pendientes[k] = setTimeout(() => enviar(k, add), ESPERA_MS);
    }

    /* ---------------- Eventos (delegados) ---------------- */

    document.addEventListener("click", (evento) => {
        const boton = evento.target.closest("[data-accion]");
        if (!boton) return;
        const add = boton.closest("[data-add]");
        if (!add) return;
        evento.preventDefault();
        const actual = cantidades[clave(add)] || 0;
        const accion = boton.dataset.accion;
        if (accion === "agregar") cambiar(add, 1);
        else if (accion === "mas") cambiar(add, actual + 1);
        else if (accion === "menos") cambiar(add, actual - 1);
        else if (accion === "quitar") cambiar(add, 0);
    });

    // Cambio de presentación en la tarjeta: actualiza precio y selector.
    document.addEventListener("change", (evento) => {
        const select = evento.target.closest("[data-pres-select]");
        if (!select) return;
        const tarjeta = select.closest(".tc-card");
        const opcion = select.selectedOptions[0];
        const add = tarjeta.querySelector("[data-add]");
        add.dataset.id = opcion.value;
        const precio = tarjeta.querySelector("[data-precio-visible]");
        if (precio) precio.textContent = moneda.format(Number(opcion.dataset.precio));
        iniciar(add);
    });

    // Flechas de las franjas horizontales.
    document.querySelectorAll(".tc-franja").forEach((franja) => {
        const pista = franja.querySelector(".tc-franja__pista");
        const flechas = franja.querySelectorAll(".tc-franja__flecha");
        if (!pista) return;
        const actualizar = () => {
            flechas.forEach((f) => {
                const dir = Number(f.dataset.scroll);
                f.disabled = dir < 0
                    ? pista.scrollLeft <= 4
                    : pista.scrollLeft + pista.clientWidth >= pista.scrollWidth - 4;
            });
        };
        flechas.forEach((f) => f.addEventListener("click", () => {
            pista.scrollBy({ left: Number(f.dataset.scroll) * pista.clientWidth * 0.9, behavior: "smooth" });
        }));
        pista.addEventListener("scroll", actualizar, { passive: true });
        window.addEventListener("resize", actualizar);
        actualizar();
    });

    /* ---------------- Carrito lateral ---------------- */

    const mini = document.getElementById("tc-mini");
    let miniTimer = null;

    function cargarMini() {
        if (!mini) return;
        const cuerpo = mini.querySelector("[data-mini-cuerpo]");
        fetch(URL_MINI, { credentials: "same-origin", headers: { "Accept": "text/html" } })
            .then((r) => r.text())
            .then((html) => {
                cuerpo.innerHTML = html;
                cuerpo.querySelectorAll("[data-add]").forEach(iniciar);
            })
            .catch(() => { cuerpo.innerHTML = '<p class="p-3 text-muted">No se pudo cargar el carrito.</p>'; });
    }

    function refrescarMini() {
        if (!mini || !mini.classList.contains("show")) return;
        clearTimeout(miniTimer);
        miniTimer = setTimeout(cargarMini, 250);
    }

    if (mini) mini.addEventListener("show.bs.offcanvas", cargarMini);

    // Atajo: "/" enfoca el buscador.
    document.addEventListener("keydown", (e) => {
        if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) {
            const buscador = document.getElementById("tc-q");
            if (buscador) { e.preventDefault(); buscador.focus(); }
        }
    });

    /* ---------------- Inicio ---------------- */

    document.querySelectorAll("[data-add]").forEach(iniciar);

    // Mensajes de Django -> avisos.
    document.querySelectorAll("[data-mensaje]").forEach((m) => {
        aviso(m.dataset.mensaje, m.dataset.nivel === "error" ? "error" : "ok");
        m.remove();
    });
})();
