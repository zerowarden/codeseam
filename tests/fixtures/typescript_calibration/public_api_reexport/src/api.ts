class Service {
  query(id: string): string {
    return id;
  }
}

export class UserApi {
  constructor(private readonly service: Service) {}

  query(id: string): string {
    return this.service.query(id);
  }
}

export class ProjectApi {
  constructor(private readonly service: Service) {}

  query(id: string): string {
    return this.service.query(id);
  }
}
