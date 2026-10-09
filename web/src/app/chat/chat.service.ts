// Author: Ignacio Rodríguez Caro
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { ChatResponse, StoreInfo } from './chat.models';

const SESSION_KEY = 'quilora.session_id';

/** Talks to the assistant API. The conversation itself is stored server-side. */
@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly http = inject(HttpClient);

  /** The configured shop's public details (name, languages, support hours). */
  store(): Observable<StoreInfo> {
    return this.http.get<StoreInfo>('/api/store');
  }

  /** Post one message, reusing the stored session ID so the server keeps the context. */
  send(message: string): Observable<ChatResponse> {
    const sessionId = this.sessionId();
    const body = sessionId ? { session_id: sessionId, message } : { message };
    return this.http
      .post<ChatResponse>('/api/chat', body)
      .pipe(tap((res) => this.storeSession(res.session_id)));
  }

  /** Drop the stored session ID; the next message starts a new conversation. */
  reset(): void {
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* storage unavailable: nothing to clear */
    }
  }

  private sessionId(): string | null {
    try {
      return sessionStorage.getItem(SESSION_KEY);
    } catch {
      return null;
    }
  }

  private storeSession(id: string): void {
    try {
      sessionStorage.setItem(SESSION_KEY, id);
    } catch {
      /* private mode: the conversation still works for this page view */
    }
  }
}
