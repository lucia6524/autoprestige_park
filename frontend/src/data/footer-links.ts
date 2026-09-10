// Données partagées pour les footers Astro.
// Les clés correspondent aux clés i18n utilisées par locales/*.json.

export interface FooterLink {
  href: string;
  i18n: string;
  text: string;
}

export const NAV_LINKS: Record<string, FooterLink> = {
  home: { href: 'index.html', i18n: 'nav.home', text: 'Accueil' },
  vehicles: { href: 'vehicules.html', i18n: 'nav.vehicles', text: 'Véhicules' },
  financing: { href: 'financement.html', i18n: 'nav.financing', text: 'Financement' },
  sell: { href: 'vendre.html', i18n: 'nav.sell', text: 'Vendre' },
  contact: { href: 'contact.html', i18n: 'nav.contact', text: 'Contact' },
};

export const SERVICE_LINKS: Record<string, FooterLink> = {
  new_vehicles: { href: '#services', i18n: 'footer.new_vehicles', text: 'Véhicules neufs' },
  used: { href: '#services', i18n: 'footer.used', text: 'Occasions' },
  financing: { href: '#services', i18n: 'footer.financing', text: 'Financement' },
  trade_in: { href: '#services', i18n: 'footer.trade_in', text: 'Reprise' },
  warranty: { href: 'garantie.html', i18n: 'nav.warranty', text: 'Garantie' },
  delivery: { href: 'livraison.html', i18n: 'nav.delivery', text: 'Livraison' },
  maintenance: { href: 'entretien.html', i18n: 'nav.maintenance', text: 'Entretien' },
  insurance: { href: 'assurance.html', i18n: 'nav.insurance', text: 'Assurance' },
};

// Taglines du bloc marque : "full" (index/404/vehicule) ou courte par défaut.
// Seule la variante full porte data-i18n="footer.tagline" (comme l'original).
export function getTagline(
  variant: 'full' | 'default' | 'custom',
  custom?: string
): { text: string; i18n: boolean } {
  if (variant === 'custom' && custom) return { text: custom, i18n: false };
  if (variant === 'full') {
    return {
      text: "Votre partenaire de confiance pour l'achat de véhicules neufs et d'occasion. Qualité, transparence et service premium.",
      i18n: true,
    };
  }
  return {
    text: "Votre partenaire de confiance pour l'achat de véhicules neufs et d'occasion.",
    i18n: false,
  };
}
