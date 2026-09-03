(() => {
  const siteUrl = 'https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/';
  const seoTitle = 'أرشيف الكويكبات | ALBAZ Asteroid Archive – NASA/JPL';
  const seoDescription = 'منصة فلكية عربية لتحليل الكويكبات والأجرام القريبة من الأرض باستخدام بيانات NASA/JPL وSBDB وSentry وJPL Horizons، مع أرشفة وبحث وتتبع مداري وتقارير علمية.';

  window.ALBAZ_WEB_CONFIG = Object.freeze({
    apiBaseUrl: 'https://omaralbaz9.pythonanywhere.com',
    siteUrl,
    seoTitle,
    seoDescription
  });

  if (typeof document === 'undefined' || !document.head) return;

  function ensureMeta(selector, attribute, key, value) {
    let node = document.head.querySelector(selector);
    if (!node) {
      node = document.createElement('meta');
      node.setAttribute(attribute, key);
      document.head.appendChild(node);
    }
    node.setAttribute('content', value);
  }

  function ensureCanonical() {
    let link = document.head.querySelector('link[rel="canonical"]');
    if (!link) {
      link = document.createElement('link');
      link.setAttribute('rel', 'canonical');
      document.head.appendChild(link);
    }
    link.setAttribute('href', siteUrl);
  }

  function ensureStructuredData() {
    const id = 'albaz-asteroid-archive-schema';
    let script = document.getElementById(id);
    if (!script) {
      script = document.createElement('script');
      script.id = id;
      script.type = 'application/ld+json';
      document.head.appendChild(script);
    }
    script.textContent = JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'WebApplication',
      name: 'أرشيف الكويكبات | ALBAZ Asteroid Archive',
      alternateName: 'ALBAZ Asteroid Archive',
      url: siteUrl,
      description: seoDescription,
      applicationCategory: 'ScienceApplication',
      operatingSystem: 'Web',
      browserRequirements: 'Requires a modern web browser with JavaScript enabled',
      inLanguage: ['ar', 'en'],
      isAccessibleForFree: true,
      author: {
        '@type': 'Person',
        name: 'الفيزيائي عمر الباز'
      }
    });
  }

  document.title = seoTitle;
  ensureCanonical();
  ensureMeta('meta[name="description"]', 'name', 'description', seoDescription);
  ensureMeta('meta[name="robots"]', 'name', 'robots', 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1');
  ensureMeta('meta[name="keywords"]', 'name', 'keywords', 'أرشيف الكويكبات, الكويكبات, الأجرام القريبة من الأرض, NASA JPL, SBDB, Sentry, JPL Horizons, asteroid archive, near earth objects');

  ensureMeta('meta[property="og:title"]', 'property', 'og:title', seoTitle);
  ensureMeta('meta[property="og:description"]', 'property', 'og:description', seoDescription);
  ensureMeta('meta[property="og:type"]', 'property', 'og:type', 'website');
  ensureMeta('meta[property="og:url"]', 'property', 'og:url', siteUrl);
  ensureMeta('meta[property="og:site_name"]', 'property', 'og:site_name', 'ALBAZ Asteroid Archive');
  ensureMeta('meta[property="og:locale"]', 'property', 'og:locale', 'ar_AR');

  ensureMeta('meta[name="twitter:card"]', 'name', 'twitter:card', 'summary');
  ensureMeta('meta[name="twitter:title"]', 'name', 'twitter:title', seoTitle);
  ensureMeta('meta[name="twitter:description"]', 'name', 'twitter:description', seoDescription);

  ensureStructuredData();
})();
