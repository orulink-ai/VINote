// IndexedDB keeps large text/version snapshots out of synchronous preference storage.
let database: Promise<IDBDatabase> | undefined;
function open() {
  database ??= new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("vinote-workspace-v2", 1);
    request.onupgradeneeded = () =>
      request.result.createObjectStore("accounts");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      database = undefined;
      reject(request.error);
    };
  });
  return database;
}
export async function readWorkspaceCache<T>(
  owner: string,
): Promise<T | undefined> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const request = db
      .transaction("accounts", "readonly")
      .objectStore("accounts")
      .get(owner);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
export async function writeWorkspaceCache(owner: string, data: unknown) {
  const db = await open();
  return new Promise<void>((resolve, reject) => {
    const transaction = db.transaction("accounts", "readwrite");
    transaction.objectStore("accounts").put(data, owner);
    transaction.oncomplete = () => resolve();
    transaction.onabort = transaction.onerror = () =>
      reject(transaction.error || new Error("本机缓存保存失败"));
  });
}
