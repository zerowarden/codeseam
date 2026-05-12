try { risky(); } catch (error) {}
try { retry(); } catch (error) {}
try { load(); } catch (error) {}

try { risky(); } catch (error) { return null; }
try { retry(); } catch (error) { return null; }
try { load(); } catch (error) { return null; }

function acceptsAny(value: any) { return value; }
function parsesAny(input: any) { return input; }
function mapsAny(record: any) { return record; }
