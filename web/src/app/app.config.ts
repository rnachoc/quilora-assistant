// Author: Ignacio Rodríguez Caro
import { provideHttpClient, withFetch } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';

/**
 * Application-wide providers: global error reporting and the HTTP client (fetch backend)
 * used by ChatService to call the assistant API.
 */
export const appConfig: ApplicationConfig = {
  providers: [provideBrowserGlobalErrorListeners(), provideHttpClient(withFetch())],
};
