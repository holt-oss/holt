/** Job ids from the API server; anything else never reaches an upstream URL. */
export const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/;

export function isJobId(id: string): boolean {
  return JOB_ID.test(id);
}
