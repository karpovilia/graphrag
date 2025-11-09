export type IHighlight = {
  start: number;
  length: number;
};
export function mergeHighlights(
  highlights: IHighlight[],
  mutateSorting: boolean = true,
): IHighlight[] {
  let temp = highlights;
  if (mutateSorting) {
    temp.sort((a, b) => a.start - b.start);
  } else {
    temp = temp.toSorted((a, b) => a.start - b.start);
  }
  const result = [temp[0]];

  for (let i = 1; i < temp.length; i++) {
    const current = temp[i];
    const last = result[result.length - 1];

    if (current.start <= last.start + last.length) {
      const end = Math.max(last.start + last.length, current.start + current.length);
      last.length = end - last.start;
    } else {
      result.push(current);
    }
  }

  return result;
}
