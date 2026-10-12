export class Team {
  constructor(private readonly _title: string, private readonly _slug: string) {}

  get title(): string {
    return this._title;
  }

  get slug(): string {
    return this._slug;
  }
}
