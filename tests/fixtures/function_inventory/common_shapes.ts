export function parseUser(raw: string) {
  return raw;
}

const score = (value: number) => {
  if (value) return value;
  return 0;
}

class Service {
  async run(item: string) {
    return item;
  }
}

const handlers = {
  load: function(id: string) {
    return id;
  }
}
