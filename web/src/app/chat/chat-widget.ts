// Author: Ignacio Rodríguez Caro
import { DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, ElementRef, OnInit, inject, signal, viewChild } from '@angular/core';

import { ChatMessage } from './chat.models';
import { ChatService } from './chat.service';

/** Example questions shown in an empty conversation; they mirror the project brief. */
const SUGGESTIONS = [
  '¿Tenéis vestidos de lino por menos de 60 €?',
  'Mido 1,68 y peso 60 kg, ¿qué talla me pido en el Iris Linen Trousers?',
  '¿Cuánto tengo para devolver algo?',
  'Where is my order 1052? liam.blanco@example.com',
];

/**
 * Floating chat widget: launcher button, message list, input box, handoff banner and a
 * 'Details' toggle that shows tools, latency and cost per turn (useful for demos).
 */
@Component({
  selector: 'app-chat-widget',
  template: `
    @if (open()) {
      <section class="panel" role="dialog" [attr.aria-label]="storeName() + ' assistant'">
        <header>
          <div>
            <strong>{{ storeName() }} · asistente</strong>
            @if (demoMode()) {
              <span class="badge" title="Scripted demo: real tools and data, no AI model">Demo</span>
            }
            <span class="sub">Atención: {{ supportHours() }}</span>
          </div>
          <div class="actions">
            <button class="ghost" (click)="showDetails.set(!showDetails())"
                    [attr.aria-pressed]="showDetails()" title="Show tools, latency and cost">
              {{ showDetails() ? 'Hide' : 'Details' }}
            </button>
            <button class="ghost" (click)="restart()" title="Start a new conversation">New</button>
            <button class="ghost" (click)="open.set(false)" aria-label="Close">✕</button>
          </div>
        </header>

        <div class="messages" #scroller aria-live="polite">
          @if (messages().length === 0) {
            @if (demoMode()) {
              <p class="hint">Demo guionizada: las herramientas, los datos y las comprobaciones de
                seguridad son reales, pero las respuestas siguen un guion. Prueba con:</p>
            } @else {
              <p class="hint">Hola, ¿en qué te ayudo? Prueba con:</p>
            }
            <div class="chips">
              @for (s of suggestions(); track s) {
                <button class="chip" (click)="send(s)">{{ s }}</button>
              }
            </div>
          }
          @for (m of messages(); track $index) {
            <div class="msg" [class]="m.role">
              <!-- Model output is untrusted: always rendered as text, never as HTML. -->
              <p>{{ m.text }}</p>
              @if (showDetails() && m.meta; as meta) {
                <dl class="meta">
                  <dt>tools</dt>
                  <dd>
                    @for (t of meta.tools; track $index) {
                      <span [class.err]="!t.ok">{{ t.name }}{{ t.ok ? '' : ' ✗ ' + t.error_code }}</span>
                    } @empty { none }
                  </dd>
                  <dt>turn</dt>
                  <dd>{{ meta.latency_ms | number: '1.0-0' }} ms · {{ meta.iterations }} model calls ·
                    {{ meta.cost_usd === null ? 'no model cost' : '~$' + meta.cost_usd }}</dd>
                  @if (meta.flags.length) {
                    <dt>flags</dt><dd>{{ meta.flags.join(', ') }}</dd>
                  }
                </dl>
              }
            </div>
          }
          @if (demoMode() && messages().length > 0 && !loading()) {
            <!-- The script only understands these, so keep them one click away. -->
            <details class="more">
              <summary>Más preguntas de la demo</summary>
              <div class="chips">
                @for (s of suggestions(); track s) {
                  <button class="chip" (click)="send(s)">{{ s }}</button>
                }
              </div>
            </details>
          }
          @if (loading()) {
            <div class="msg assistant typing" aria-label="The assistant is typing"><span></span><span></span><span></span></div>
          }
        </div>

        @if (ticketId()) {
          <p class="handoff">Te hemos pasado con el equipo de atención al cliente · ticket {{ ticketId() }}</p>
        }

        <form (submit)="$event.preventDefault(); send(draft())">
          <textarea rows="1" [value]="draft()" (input)="draft.set($any($event.target).value)"
                    (keydown.enter)="$event.preventDefault(); send(draft())"
                    placeholder="Escribe tu mensaje…" maxlength="2000" aria-label="Message"></textarea>
          <button type="submit" [disabled]="loading() || !draft().trim()">Enviar</button>
        </form>
      </section>
    } @else {
      <button class="launcher" (click)="open.set(true)" aria-label="Open the assistant">
        <span aria-hidden="true">💬</span> ¿Te ayudo?
      </button>
    }
  `,
  styleUrl: './chat-widget.css',
  imports: [DecimalPipe],
})
export class ChatWidget implements OnInit {
  private readonly chat = inject(ChatService);
  private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');

  protected readonly suggestions = signal<string[]>(SUGGESTIONS);
  protected readonly demoMode = signal(false);
  protected readonly open = signal(false);
  protected readonly showDetails = signal(false);
  protected readonly loading = signal(false);
  protected readonly draft = signal('');
  protected readonly messages = signal<ChatMessage[]>([]);
  protected readonly ticketId = signal<string | null>(null);
  protected readonly storeName = signal('Tienda');
  protected readonly supportHours = signal('');

  /** Load the shop's name and support hours, so one widget serves any configured store. */
  ngOnInit(): void {
    this.chat.store().subscribe({
      next: (info) => {
        this.storeName.set(info.name);
        this.supportHours.set(info.support_hours);
        this.demoMode.set(info.demo_mode);
        if (info.suggestions?.length) this.suggestions.set(info.suggestions);
      },
      error: () => {
        /* keep the generic defaults; chatting still works */
      },
    });
  }

  /** Send a customer message to the API and append the reply (or a friendly error). */
  send(text: string): void {
    const message = text.trim();
    if (!message || this.loading()) return;
    this.draft.set('');
    this.push({ role: 'user', text: message });
    this.loading.set(true);

    this.chat.send(message).subscribe({
      next: (res) => {
        this.push({ role: 'assistant', text: res.reply, meta: res.meta });
        if (res.ticket_id) this.ticketId.set(res.ticket_id);
        this.loading.set(false);
      },
      error: (err: HttpErrorResponse) => {
        if (err.status === 404) this.chat.reset(); // session expired server-side
        const text =
          err.status === 409
            ? 'Tu mensaje se cruzó con otro. Envíalo de nuevo, por favor.'
            : err.status === 429
              ? 'La demo ha alcanzado el límite de mensajes de hoy. Vuelve mañana, por favor.'
              : 'No he podido conectar con el asistente. Inténtalo de nuevo en un momento.';
        this.push({ role: 'error', text });
        this.loading.set(false);
      },
    });
  }

  /** Forget the current session and clear the screen to start a new conversation. */
  restart(): void {
    this.chat.reset();
    this.messages.set([]);
    this.ticketId.set(null);
  }

  /** Append a message and keep the list scrolled to the newest one. */
  private push(message: ChatMessage): void {
    this.messages.update((list) => [...list, message]);
    queueMicrotask(() => {
      const el = this.scroller()?.nativeElement;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
}
