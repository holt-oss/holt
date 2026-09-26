// Vite's `?raw` import: the file's text as a string (used to read stylesheets in tests).
declare module "*?raw" {
  const text: string;
  export default text;
}
