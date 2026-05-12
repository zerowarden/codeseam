try { risky(); } catch (error) { throw error; }
try { retry(); } catch (error) { console.error(error); }
try { load(); } catch (error) { return undefined; }

function acceptsString(value: string) { return value; }
function acceptsUnknown(value: unknown) { return value; }
function acceptsRecord(value: Record<string, string>) { return value; }
