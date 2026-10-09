// Author: Ignacio Rodríguez Caro
import { Component } from '@angular/core';

import { ChatWidget } from './chat/chat-widget';

/** A minimal storefront so the widget can be demoed in context. */
@Component({
  selector: 'app-root',
  imports: [ChatWidget],
  template: `
    <header class="top">
      <span class="logo">Quilora</span>
      <nav><a>Mujer</a><a>Hombre</a><a>Accesorios</a></nav>
    </header>

    <main>
      <section class="hero">
        <p class="eyebrow">Colección otoño</p>
        <h1>Lino, algodón orgánico y lana merino.</h1>
        <p>Envío gratis en península desde 50 €. Devoluciones en 30 días.</p>
      </section>

      <p class="notice">
        Tienda ficticia para demostrar un asistente de IA. Todos los productos, pedidos y
        clientes son sintéticos.
      </p>
    </main>

    <app-chat-widget />
  `,
  styles: `
    .top { display: flex; justify-content: space-between; align-items: center;
           padding: 18px 32px; border-bottom: 1px solid var(--line); }
    .logo { font: 600 26px var(--font-display); letter-spacing: 0.04em; }
    nav { display: flex; gap: 20px; font-size: 14px; color: var(--muted); }
    main { max-width: 960px; margin: 0 auto; padding: 72px 32px; }
    .eyebrow { text-transform: uppercase; letter-spacing: 0.14em; font-size: 12px;
               color: var(--accent); margin: 0; }
    h1 { font: 500 clamp(36px, 6vw, 64px) / 1.05 var(--font-display); margin: 12px 0 16px; }
    .hero p:last-child { color: var(--muted); font-size: 18px; }
    .notice { margin-top: 64px; padding: 12px 16px; border: 1px dashed var(--line);
              border-radius: 10px; font-size: 13px; color: var(--muted); max-width: 520px; }
    @media (max-width: 600px) { nav { display: none; } .top { padding: 16px; } main { padding: 40px 16px; } }
  `,
})
export class App {}
