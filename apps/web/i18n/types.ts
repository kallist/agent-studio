type WidenMessages<T> = {
  [K in keyof T]: T[K] extends string ? string : WidenMessages<T[K]>;
};
type LeafPaths<T> = {
  [K in keyof T & string]: T[K] extends string
    ? K
    : T[K] extends Record<string, unknown>
      ? `${K}.${LeafPaths<T[K]>}`
      : never;
}[keyof T & string];

export type MessageShape<T> = WidenMessages<T>;
export type MessageKey<T> = LeafPaths<T>;
export type TranslationValues = Record<string, string | number>;
