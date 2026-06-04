/**
 * Shared UI utilities for agno-plus applications.
 */

/**
 * Strip the sd_{domain_id_short}_ prefix from a dynamic table name,
 * returning the user-visible label.
 *
 * Example: "sd_abcd1234_invoices" → "invoices"
 */
export function tableLabel(domainId: string, tableName: string): string {
  const prefix = `sd_${domainId.replace(/-/g, "").slice(0, 8)}_`;
  return tableName.startsWith(prefix) ? tableName.slice(prefix.length) : tableName;
}

export const SOURCE_ICONS: Record<string, string> = {
  spreadsheet: "📊",
  image: "🖼️",
  audio: "🎵",
  structured: "🗄️",
  text: "📄",
};

export function sourceIcon(sourceType: string): string {
  return SOURCE_ICONS[sourceType] ?? "📄";
}
