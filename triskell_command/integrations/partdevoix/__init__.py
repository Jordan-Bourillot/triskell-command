"""La Part de Voix — moteur de la 2e offre Triskell Studio.

Mesure la présence d'entreprises dans les réponses des IA grand public
(ChatGPT, Perplexity, Gemini en mode recherche web), génère les audits
personnalisés envoyés aux prospects, et fait tourner le pilote interne.

Modules :
- moteur.py : interrogation des IA web + extraction des noms cités
- audit.py  : audit personnalisé par prospect (3 issues) + page HTML
- pilote.py : mesure pilote interne (questions traitées vs témoins)
"""
