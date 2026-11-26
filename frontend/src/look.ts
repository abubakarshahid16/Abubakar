/** The way-back switch of the new look (owner, 26 Nov 2026): off unless the web page is started with VITE_UI_NEW_LOOK=true. One home:
 *  App stamps `data-look` from it, and the few parts whose ORDER or folding changes with the look read it here (look only; the same
 *  words, numbers and actions either way). */
export const NEW_LOOK = import.meta.env.VITE_UI_NEW_LOOK === "true";
