function identity<T>(value: T): T;
function identity<T>(value: T): T { return value; }
function split<T, U>(value: T): U;
function split<T, U>(value: T): U { throw new Error("no"); }

function overloaded(value: string): string;
function overloaded(value: number): number;
function overloaded(value: string | number) { return value; }
