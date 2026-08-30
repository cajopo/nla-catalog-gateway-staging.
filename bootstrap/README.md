# Sorgente temporaneo già caricato

I cinque file `source.tar.gz.b64.part-*` ricompongono il sorgente revisionato del gateway.

SHA-256 richiesto dopo la decodifica Base64:

`8bd0ef386f4187f8b7c7440af1b082a8256c0be5f5172fd3aa1bea60ae4d2541`

Il workflow `Bootstrap source and build verified catalog` interrompe l’esecuzione se manca un frammento, se l’hash non coincide, se l’archivio contiene percorsi non sicuri o se una verifica del catalogo fallisce. Rimuove l’intera cartella `bootstrap/` soltanto dopo una build riuscita.
