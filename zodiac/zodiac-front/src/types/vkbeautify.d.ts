declare module "vkbeautify" {
  interface VkBeautify {
    xml: (text: string, indent?: number | string) => string;
    xmlmin: (text: string, preserveComments?: boolean) => string;
    json: (text: string, indent?: number | string) => string;
    jsonmin: (text: string) => string;
    css: (text: string, indent?: number | string) => string;
    cssmin: (text: string) => string;
    sql: (text: string, indent?: number | string) => string;
    sqlmin: (text: string) => string;
  }

  const vkbeautify: VkBeautify;
  export default vkbeautify;
}
