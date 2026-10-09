// Author: Ignacio Rodríguez Caro
// Entry point: starts the Angular application with the root component and its providers.
import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';

bootstrapApplication(App, appConfig)
  .catch((err) => console.error(err));
