/** Prefer file-manager entries over their text or thumbnail representations. */
export interface UploadClipboard {
  readFiles(): Promise<string[]>;
  readText(): Promise<string>;
  readImage(): Promise<{ url: string } | null>;
}

export async function readUploadClipboard(
  clipboard: UploadClipboard,
  acceptImage: boolean,
): Promise<{ paths: string[] } | { image: string } | null> {
  const files = await clipboard.readFiles();
  if (files.length) return { paths: files };
  if (acceptImage) {
    const image = await clipboard.readImage();
    if (image) return { image: image.url };
  }
  // A copied path list must never become a single path containing newlines.
  const paths = (await clipboard.readText())
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const quote = line[0];
      return (quote === '"' || quote === "'") && line.endsWith(quote) ? line.slice(1, -1) : line;
    });
  return paths.length && paths.every((path) => /^(?:\.\.?\/|\/|file:|[A-Za-z]:[\\/])/.test(path))
    ? { paths }
    : null;
}
