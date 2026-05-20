/* MailAddressBook — carnet local des adresses mail utilisées
 *
 * Mémorise les adresses du To/Cc/Cci à chaque envoi (mail_send,
 * mail_schedule, mail_send_reply) et propose une autocomplétion
 * dans les champs du composer.
 *
 * État : localStorage 'tc-mail-address-book' = [{ email, count, last_used }]
 *
 * API :
 *   MailAddressBook.record(emails)   // un email ou un tableau
 *   MailAddressBook.search(query, n) // suggestions triées
 *   MailAddressBook.forget(email)    // supprime une entrée
 *   MailAddressBook.all()            // tout, trié par usage
 */

const MailAddressBook = {
  STORAGE_KEY: 'tc-mail-address-book',
  MAX_ENTRIES: 300,

  _emailRegex: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,

  _load() {
    try {
      const raw = localStorage.getItem(this.STORAGE_KEY);
      const list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) { return []; }
  },

  _save(list) {
    try {
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(list));
    } catch (e) { /* quota plein ou storage désactivé : on ignore */ }
  },

  /** Enregistre une adresse (ou un tableau) après envoi réussi. */
  record(emails) {
    if (!emails) return;
    if (typeof emails === 'string') emails = [emails];
    if (!Array.isArray(emails)) return;

    const list = this._load();
    const now = Date.now();
    let touched = false;

    emails.forEach(raw => {
      if (!raw || typeof raw !== 'string') return;
      const email = raw.trim().toLowerCase();
      if (!this._emailRegex.test(email)) return;

      const existing = list.find(e => e.email === email);
      if (existing) {
        existing.count = (existing.count || 0) + 1;
        existing.last_used = now;
      } else {
        list.push({ email, count: 1, last_used: now });
      }
      touched = true;
    });

    if (!touched) return;

    list.sort((a, b) => (b.last_used || 0) - (a.last_used || 0));
    this._save(list.slice(0, this.MAX_ENTRIES));
  },

  /** Renvoie jusqu'à `limit` suggestions classées par pertinence. */
  search(query, limit = 6) {
    const q = (query || '').trim().toLowerCase();
    let list = this._load();

    if (q) {
      list = list.filter(e => e.email.includes(q));
    }

    list.sort((a, b) => {
      const aPrefix = a.email.startsWith(q) ? 0 : 1;
      const bPrefix = b.email.startsWith(q) ? 0 : 1;
      if (aPrefix !== bPrefix) return aPrefix - bPrefix;
      if ((b.count || 1) !== (a.count || 1)) return (b.count || 1) - (a.count || 1);
      return (b.last_used || 0) - (a.last_used || 0);
    });

    return list.slice(0, limit);
  },

  /** Supprime une adresse du carnet. */
  forget(email) {
    const e = (email || '').trim().toLowerCase();
    if (!e) return;
    const list = this._load().filter(x => x.email !== e);
    this._save(list);
  },

  /** Tout le carnet, trié par usage puis récence. */
  all() {
    const list = this._load();
    list.sort((a, b) =>
      (b.count || 1) - (a.count || 1) ||
      (b.last_used || 0) - (a.last_used || 0)
    );
    return list;
  },

  /** Vide complètement le carnet. */
  clear() {
    try { localStorage.removeItem(this.STORAGE_KEY); } catch (e) {}
  },
};

window.MailAddressBook = MailAddressBook;
