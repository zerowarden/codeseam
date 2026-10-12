export class MemberRecord {
  constructor(private readonly _name: string, private readonly _email: string) {}

  get name(): string {
    return this._name;
  }

  get email(): string {
    return this._email;
  }
}
