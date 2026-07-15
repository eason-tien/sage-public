export function createSingleFlight(loader) {
  const inFlight = new Map();

  return function load(key) {
    if (inFlight.has(key)) return inFlight.get(key);
    const promise = Promise.resolve(loader(key));
    inFlight.set(key, promise);
    promise.then(() => inFlight.delete(key));
    return promise;
  };
}
