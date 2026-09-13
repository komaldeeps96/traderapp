/** The last result, returned again while every argument is the same object. */
export function memoizeLast<Args extends unknown[], R>(
  compute: (...args: Args) => R,
): (...args: Args) => R {
  let last: { args: Args; result: R } | null = null;
  return (...args: Args): R => {
    if (
      last !== null &&
      last.args.length === args.length &&
      last.args.every((arg, index) => Object.is(arg, args[index]))
    ) {
      return last.result;
    }
    const result = compute(...args);
    last = { args, result };
    return result;
  };
}
