class ViewApi {
  public async addScript(handle: ViewHandle, scriptPath: string): Promise<void> {
    return this.controller(handle).addScript(scriptPath);
  }

  public on(eventName: string, callback: Listener): void {
    eventManager.on(eventName, callback);
  }
}
