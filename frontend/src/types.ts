// Options du Footer partagé — utilisées par Footer.astro et Layout.astro
export interface FooterOptions {
  /** Colonnes Navigation / Services : clés de footer-links.ts */
  nav?: string[];
  services?: string[];
  /** Bloc contact : lien WhatsApp et/ou adresse */
  contactWhatsapp?: boolean;
  contactAddress?: 'full' | 'short' | false;
  /** Tagline du bloc marque */
  tagline?: 'full' | 'default' | 'custom';
  taglineText?: string;
  /** Ligne légale : liens complets (Mentions/Cookies/CGV) ou texte court */
  legal?: 'full' | 'short';
}
