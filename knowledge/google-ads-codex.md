> **Note de maintenance (version d'export).** Ce fichier est une copie anonymisée,
> maintenue à la main, de `knowledge/google-ads-codex.md` (dépôt interne de Matt). Le
> codex vivant cite des cas clients réels ; cette version d'export ne doit jamais en
> laisser fuiter la moindre trace (nom de client, domaine, nom de produit, identifiant
> de campagne ou de page). À chaque évolution du codex source, reporter ici la leçon
> anonymisée (Symptôme / Cause / Parade / Contrôle), jamais le cas client brut.

# Codex Google Ads : mémoire technique de La Régie

Source de vérité unique des pièges rencontrés en pilotant des comptes Google Ads (agents `pm-*`). Consigné une seule fois ici ; les agents `pm-buyer`, `pm-tracking`, `pm-feed`, `pm-analyst` et `pm-qc` le chargent au lieu de re-diagnostiquer. On ne duplique JAMAIS un piège dans un prompt d'agent : on pointe vers ce fichier.

Rituel post-mortem : tout nouveau piège découvert en audit, en application ou en QC est ajouté ici (avec sa date), après validation Matt.

## Règles absolues

- **Données LIVE uniquement.** Jamais de fichiers `ads.json` ou d'exports locaux périmés : toujours l'API Google Ads en direct, ou un export manuel frais du jour. Une décision d'optimisation basée sur des données périmées est une faute.
- **Mode hybride.** L'agence opère, elle ne se contente pas de conseiller. Elle applique en live ce qui est sûr et réversible (Tier 1), elle laisse en recommandation validée par l'humain tout ce qui est sensible (Tier 2), elle ne touche jamais au site sans prévenir + backup + GO explicite (Tier 3), elle bloque tout ce qui viole le dossier réglementaire (Tier 4).
- **Standard "agence pro" non optionnel.** Chaque agent doit par défaut : récupérer la data de façon granulaire (pas d'agrégats superficiels) ; faire des méta-analyses et des audits en profondeur (croisements inter-dimensions, pas des checklists isolées) ; venir avec des idées et des hypothèses de test, pas seulement des correctifs ; justifier systématiquement chaque recommandation avec preuve (data), mécanisme (pourquoi ça marche ou ça casse) et impact estimé en EUR ; produire des rapports poussés, jamais de simples listes d'optimisations ; respecter le dossier client (secteur, réglementation) dès la première action.
- **CA réel = back-office (WooCommerce ou équivalent), jamais GA4.** GA4 sert à comprendre le comportement et le funnel, jamais à trancher une décision budgétaire ou à évaluer la performance réelle d'une campagne. Le chiffre d'affaires de référence est toujours l'API du back-office e-commerce, jamais les conversions ou le revenu rapportés par GA4 ou par Google Ads.
- **Priorisation par impact EUR.** Toute recommandation, tout arbitrage, tout ordre de traitement dans un rapport est trié par impact chiffré en euros, pas par facilité de mise en oeuvre ni par volume de mots.

---

## Classification des 4 tiers de gates

`pm-qc` vérifie la classification de chaque changement avant application. La classification vit ici, cohérente et enrichie au fil des post-mortems.

| Tier | Nature | Exemples | Traitement |
|---|---|---|---|
| **Tier 1, AUTO** | Sûr, réversible, ne bouge jamais le niveau de dépense | Négatifs en exact ou en phrase (jamais en large sur un mot-clé qui convertit) ; exclusions de produit dans un listing group ; ajouts de titres/descriptions RSA ou d'assets ; ajustements d'enchères horaires (dayparting) ; audiences ajoutées en observation | Appliqué en Phase 4, toujours loggé, justifié, listé dans le rapport. Rollback 1 clic. |
| **Tier 2, GATE** | Sensible, impact direct sur la dépense ou la structure du compte | Changement de budget (hausse ou baisse) ; création d'une nouvelle campagne ; pause ou suppression d'une campagne ou d'un ad group ; changement de stratégie d'enchères (tCPA/tROAS) ; changement de statut d'une action de conversion ; grosses listes de négatifs ; coupes de cannibalisation ; tout ce qui touche la campagne de marque défensive | Retenu à la Gate 2 `apply_sensible`, validé item par item avec Matt avant application. |
| **Tier 3, SITE / EXTERNE** | Touche le site ou l'infrastructure hors du compte Ads | Landing pages ; snippets de tracking ; règles de flux qui modifient le site (Merchant Center, GTM) | Toujours gate + backup. Prévenir, proposer une sauvegarde, obtenir un GO explicite. Jamais en auto. Création de landing page = relais vers l'agent ou l'équipe compétente pour le site ; fix technique = spec de dev transmise. |
| **Tier 4, INTERDIT** | Viole le dossier réglementaire du client | Allégations santé interdites (secteur paramédical/dispositif médical) ; mots-clés hors politique Google Ads | `pm-qc` bloque. Non proposable sans alerte explicite, même en recommandation. |

Principe verrouillant : rien de silencieux. Même les changements Tier 1 sont dans le change-log et dans le rapport client. Tout est réversible ou documenté comme tel.

---

## Les 11 pièges

### 1. Faux positif de gaspillage (0 conversion Ads ne veut pas dire 0 vente)
- **Symptôme** : un mot-clé, un produit ou une campagne affiche 0 conversion sur 30 jours dans Google Ads et semble candidat à l'exclusion ou à la pause.
- **Cause** : Google Ads ne voit que ce qu'il a pu attribuer (cookies, fenêtre d'attribution, consentement). Un produit peut se vendre par un autre canal (organique, direct, offline) sans qu'Ads le sache, ou l'attribution peut être cassée (voir piège 3) sans que la vente réelle ait disparu.
- **Parade (audit/optimisation)** : avant toute exclusion ou coupe basée sur "0 conversion", croiser systématiquement avec le CA réel du back-office du produit ou de la thématique sur une fenêtre longue (12 mois). Exemple constaté chez un client e-commerce paramédical : un produit accessoire à 0 vente sur 12 mois côté back-office = vrai poids mort, exclusion justifiée. Un autre produit à 0 conversion Ads mais avec un volume annuel de ventes réelles significatif côté back-office = à garder, le problème est l'attribution, pas le produit.
- **Contrôle (QC)** : toute exclusion produit ou coupe de mot-clé motivée par "0 conversion" doit citer le chiffre du back-office correspondant dans la justification, sinon `pm-qc` renvoie en FIX.

### 2. Campagne de marque défensive
- **Symptôme** : une campagne sur le nom de marque affiche un ROAS très élevé, tentant de justifier une baisse de budget ailleurs pour la scaler, ou à l'inverse une tentation de la couper car "elle ne sert à rien, les gens tapent le nom de toute façon".
- **Cause** : le ROAS d'une campagne de marque est gonflé par des conversions largement incrémentales à zéro : l'utilisateur qui tape le nom de la marque aurait cliqué sur le lien organique ou tapé l'URL directement. La campagne protège surtout la position contre les concurrents qui enchérissent sur la marque.
- **Parade (audit/optimisation)** : ne jamais juger la performance de cette campagne sur son ROAS apparent (biaisé structurellement), ne jamais la couper (elle protège la position face aux enchérisseurs concurrents), ne jamais la scaler sur la base de son ROAS (le budget marginal n'apporte pas de volume incrémental proportionnel). Elle se pilote sur l'impression share et la présence de concurrents sur les enchères, pas sur le ROAS.
- **Contrôle (QC)** : tout changement touchant la campagne de marque défensive (budget, pause, enchères) est automatiquement Tier 2, quelle que soit sa taille. `pm-qc` vérifie qu'aucune recommandation ne s'appuie sur le ROAS brut de cette campagne comme argument de scaling ou de coupe.

### 3. Artefact d'attribution lié à la passerelle de paiement
- **Symptôme** : chute apparente des conversions Google Ads sur une période, sans baisse de trafic ni de qualité de trafic constatée.
- **Cause** : le retour depuis certaines passerelles de paiement (constaté avec une passerelle de paiement tierce répandue en Europe) casse la session utilisateur et réattribue la conversion au referral (la passerelle elle-même) plutôt qu'à Google Ads. La vente a bien eu lieu, mais le clic Ads d'origine n'est plus crédité.
- **Parade (audit/optimisation)** : avant toute réaction budgétaire à une chute de conversions Ads (baisse de budget, pause, changement de stratégie d'enchères), trancher systématiquement avec le CA réel du back-office sur la même période. Si le CA back-office est stable ou en hausse alors que les conversions Ads chutent, la cause est un artefact d'attribution, pas une dégradation de la performance média. Remonter le sujet à `pm-tracking` pour investigation de l'attribution, pas à `pm-buyer` pour une action budgétaire.
- **Contrôle (QC)** : toute alerte de "chute de conversions" doit être accompagnée du chiffre du back-office de la même période avant toute proposition de changement de budget ou d'enchères. Sans ce croisement, `pm-qc` bloque la recommandation.

### 4. Double comptage GA4 (envoi client + serveur désaligné)
- **Symptôme** : les conversions ou le revenu remontés dans GA4 sont significativement supérieurs au CA réel du back-office (constaté à environ +30 pour cent chez un client).
- **Cause** : deux canaux d'envoi de l'événement d'achat coexistent (par exemple GTM côté client et un plugin de tracking serveur côté site) sans `transaction_id` et/ou `client_id` alignés entre les deux, ce qui fait compter le même achat deux fois.
- **Parade (audit/optimisation)** : ne jamais piloter une décision Ads (budget, enchères, jugement de performance) sur les conversions ou le revenu GA4 tant que ce double comptage n'est pas corrigé. Le fix (alignement des IDs, déduplication, conditionnement de l'envoi serveur au refus de cookies) est du ressort de `pm-tracking` et touche potentiellement le site : à qualifier en Tier 3 si la correction nécessite une modification de snippet sur le site.
- **Contrôle (QC)** : `pm-qc` vérifie que tout rapport ou toute recommandation citant un chiffre GA4 comme preuve de performance croise ce chiffre avec le CA back-office réel ; un écart supérieur à quelques points de pourcentage est un signal de double comptage à signaler, pas à ignorer.

### 5. Négatif large dangereux sur un terme sensible
- **Symptôme** : un mot-clé qui convertissait bien disparaît soudainement du trafic, ou le volume chute fortement après l'ajout d'un négatif jugé "évident".
- **Cause** : la correspondance des mots-clés négatifs Google Ads opère au mot entier, jamais en sous-chaîne : un négatif large "pharmacie" ne bloque donc pas "parapharmacie", qui est un mot distinct. Le vrai risque est ailleurs : un négatif large posé sur un mot générique qui figure, en mot entier, dans des requêtes qui convertissent bloque toutes ces requêtes. Exemple : chez un client paramédical, un négatif large posé sur un terme cœur de gamme (un mot entier qui décrit la fonction ou la zone d'usage du produit phare) tuerait l'essentiel des requêtes converties, car ce mot entier apparaît dans la majorité des recherches gagnantes.
- **Parade (build/optimisation)** : tout négatif touchant un terme générique, un nom d'enseigne ou un terme sensible se pose exclusivement en correspondance exacte ou en expression (phrase), jamais en large sans réflexion. Avant d'exclure une famille de requêtes (par exemple "pharmacie" / "parapharmacie"), vérifier au mot entier, dans le rapport de termes de recherche, lesquelles convertissent réellement : un négatif exact posé sur "parapharmacie" ou sur une enseigne (par exemple un nom de distributeur) peut exclure à tort une requête distributeur qui convertit, alors même qu'un négatif "pharmacie" seul ne la toucherait pas.
- **Contrôle (QC)** : `pm-qc` vérifie la correspondance de chaque négatif ajouté en Tier 1 ; tout négatif large sur un terme court ou générique est renvoyé en FIX, à reposer en exact/phrase ou à faire remonter en Tier 2 pour arbitrage humain.

### 6. Restrictions santé / paramédical
- **Symptôme** : une annonce, une extension ou un mot-clé est refusé, limité, ou expose le compte à un risque de suspension sur un compte du secteur santé ou dispositif médical.
- **Cause** : la politique Google Ads relative à la santé (annonceurs de dispositifs médicaux, allégations thérapeutiques, produits de santé réglementés en UE) interdit certaines allégations (guérison, traitement, promesse de résultat médical) et contraint certains mots-clés (pathologies nommées, comparaisons thérapeutiques).
- **Parade (audit/optimisation)** : dès la Phase 0 (dossier client), tout compte identifié comme paramédical ou dispositif médical charge la politique Google Ads santé correspondante et la liste des allégations interdites et mots-clés contraints avant toute action, y compris avant les audits de tier 1. Aucune allégation santé non vérifiée par le dossier ne doit apparaître dans une recommandation de copy ou de mot-clé.
- **Contrôle (QC)** : tout ce qui viole le dossier réglementaire (allégation interdite, mot-clé hors politique) est Tier 4 : `pm-qc` bloque la recommandation ou l'action, sans exception, et alerte explicitement au lieu de la proposer silencieusement.

### 7. Budget bridé (impression share perdue au budget)
- **Symptôme** : une campagne performante affiche une impression share perdue au budget élevée : elle pourrait capter plus de volume rentable mais le budget quotidien la plafonne.
- **Cause** : sous-dimensionnement du budget par rapport à la demande captable, souvent hérité d'un arbitrage ancien jamais revu à la lumière de la performance actuelle.
- **Parade (audit/optimisation)** : identifier et chiffrer systématiquement l'impression share perdue au budget par campagne, avec estimation de l'impact EUR d'une augmentation (volume incrémental estimé x taux de conversion x panier moyen, ou marge). Cette identification est une action d'audit Tier 1 (constat, pas d'action sur le compte), mais toute hausse de budget qui en découle est un changement Tier 2 : elle se propose, chiffrée et justifiée, elle ne s'applique jamais automatiquement.
- **Contrôle (QC)** : `pm-qc` vérifie qu'aucune hausse de budget n'a été appliquée sans passage par la Gate 2, même quand l'impression share perdue au budget est un signal fort et non ambigu.

### 8. CA accessoire élevé n'est pas une opportunité Shopping
- **Symptôme** : un accessoire ou un consommable affiche un CA back-office élevé (par exemple un accessoire de rechange à quelques milliers d'euros par an) alors qu'il est absent du flux Shopping. Tentation de conclure à une opportunité d'acquisition Shopping non captée.
- **Cause** : Shopping capte de l'intention de recherche EXTERNE nouvelle. Or le CA d'un accessoire peut être entièrement non incrémental en Shopping pour deux raisons : soit la demande est groupée à la vente initiale (l'accessoire s'achète avec le produit principal, jamais via une recherche dédiée), soit le produit est exclusif au site (aucune recherche Shopping concurrentielle possible, le réachat se fait en direct sur le site). Croiser le CA ne suffit pas : c'est le COMPORTEMENT d'achat qui tranche. Cousin du piège 1.
- **Parade (audit/optimisation)** : avant de proposer l'inclusion Shopping d'un accessoire ou consommable, se demander explicitement "un NOUVEAU client chercherait-il ce produit sur Google ?". Si la réponse est non (achat groupé à la vente initiale, ou produit propriétaire exclusif au site), le levier de croissance n'est pas Shopping mais le on-site (cross-sell au panier, relance post-achat, bundle). Ne jamais financer une campagne d'acquisition sur une demande non incrémentale.
- **Contrôle (QC)** : toute proposition d'inclusion Shopping d'un accessoire justifiée par le seul CA back-office, sans analyse du comportement d'achat (groupé vs recherche dédiée, exclusif vs concurrentiel), est renvoyée en FIX. Découvert au rodage d'un client pilote, une réactivation de plusieurs accessoires proposée sur la seule foi du CA a été invalidée sur ce motif.

### 9. Réécriture de titre produit : Tier 3, jamais Tier 1
- **Symptôme** : une optimisation de titre de fiche produit (pour améliorer le matching Shopping) est proposée comme un ajustement d'attribut de flux réversible, donc classée Tier 1 automatique.
- **Cause** : un titre de fiche produit n'est pas un attribut Ads, c'est une donnée e-commerce/flux GLA. Le modifier touche le storefront (le titre s'affiche sur le site) et peut avoir un effet de bord SEO (le titre indexé change). Réversible n'égale pas sans conséquence.
- **Parade (build/optimisation)** : toute modification d'un attribut de flux qui est aussi une donnée produit affichée sur le site (titre, description, image) est Tier 3 : backup + GO, exécution déléguée (back-office/GLA via l'agent technique ou l'intégrateur), jamais la couche apply automatique Ads.
- **Contrôle (QC)** : `pm-qc` reclasse en Tier 3 tout item de réécriture de titre/description/image produit tagué Tier 1 ou 2. Découvert au rodage d'un client pilote.

### 10. Ajout de mot-clé : Tier 2 par défaut (cannibalisation)
- **Symptôme** : l'ajout d'un nouveau mot-clé performant (repéré dans les search terms d'une campagne Shopping, par exemple) est proposé comme une action sûre Tier 1.
- **Cause** : ajouter un mot-clé en Search sur un terme déjà capté en Shopping déplace de l'allocation entre campagnes (cannibalisation), et l'add_keyword n'était pas explicitement classé dans la table des tiers, laissant croire à une action anodine.
- **Parade (audit/optimisation)** : l'ajout d'un mot-clé qui déplace de l'allocation entre campagnes (Shopping vers Search notamment) est Tier 2 par défaut, tant que la cannibalisation n'est pas écartée par la donnée. Un ajout de mot-clé purement additif sur un terme non couvert ailleurs peut rester Tier 1, à justifier.
- **Contrôle (QC)** : `pm-qc` vérifie qu'un add_keyword tagué Tier 1 ne recouvre pas un terme déjà servi par une autre campagne ; sinon FIX vers Tier 2. Découvert au rodage d'un client pilote.

### 11. Ajustement d'enchère au scope compte : toujours exclure la marque
- **Symptôme** : un ajustement d'enchère (dayparting, bid modifier appareil/audience) est appliqué au scope "toutes campagnes actives", englobant sans le vouloir la campagne de marque défensive.
- **Cause** : un ajustement global réduit en aveugle la présence de la campagne de marque, qui obéit à une logique distincte (défense de position, pilotée sur l'impression share, jamais sur le ROAS ni sur l'efficacité horaire moyenne du compte). C'est le piège 2 par effet de bord d'un changement conçu pour d'autres campagnes.
- **Parade (audit/optimisation)** : tout ajustement d'enchère au scope multi-campagnes doit nommer explicitement les campagnes visées et EXCLURE la campagne de marque, ou passer la part marque en Tier 2. Ne jamais laisser un scope "toutes campagnes" avaler la marque.
- **Contrôle (QC)** : `pm-qc` vérifie le scope de tout ajustement d'enchère ; si la campagne de marque est incluse sans justification explicite, FIX (exclure la marque du scope, ou Tier 2 pour la part marque). Découvert au rodage d'un client pilote.

---

## Rituel de fin

Tout nouveau piège découvert en audit, en application (Phase 4) ou en QC (Phase 5) est ajouté ici selon le même format (Symptôme / Cause / Parade / Contrôle), daté, après validation de Matt. On ne le documente jamais uniquement dans un prompt d'agent ou dans un rapport client ponctuel : le codex est la seule source de vérité, chargée par tous les agents `pm-*`.

---

Historique :
- Création. Pièges 1 à 7 formalisés à partir du rodage d'un compte client pilote et de la spec de conception de La Régie.
- Pièges 8 à 11 ajoutés après le premier cycle complet de rodage du client pilote (dry-run). Piège 8 (CA accessoire vs opportunité Shopping) découvert par Matt à la Gate 1 ; pièges 9-11 (titre produit = Tier 3, add_keyword = Tier 2, ajustement d'enchère au scope compte exclut la marque) remontés par pm-qc en contrôle pré-Gate 1. Validés par Matt.
