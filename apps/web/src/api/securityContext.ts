class SecurityContextLifecycle {
  private currentGeneration = 0;
  private controllers = new Set<AbortController>();

  public generation(): number {
    return this.currentGeneration;
  }

  public createAbortController(): AbortController {
    const controller = new AbortController();
    this.controllers.add(controller);
    controller.signal.addEventListener('abort', () => this.controllers.delete(controller), {
      once: true,
    });
    return controller;
  }

  public release(controller: AbortController): void {
    this.controllers.delete(controller);
  }

  public advance(): number {
    this.currentGeneration += 1;
    for (const controller of this.controllers) controller.abort();
    this.controllers.clear();
    return this.currentGeneration;
  }
}

export const securityContext = new SecurityContextLifecycle();
