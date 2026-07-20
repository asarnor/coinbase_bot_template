/**
 * Resolve the ccxt Coinbase implementation for the requested environment.
 *
 * Current ccxt versions expose Advanced Trade as `coinbase`. Older releases
 * used `coinbaseadvanced`. Sandbox must remain on `coinbaseexchange`, the only
 * Coinbase implementation with Exchange sandbox endpoints.
 */
export function resolveCoinbaseExchange(ccxtNamespace, useSandbox) {
    const candidateIds = useSandbox
        ? ['coinbaseexchange']
        : ['coinbase', 'coinbaseadvanced', 'coinbaseexchange'];

    for (const exchangeId of candidateIds) {
        const ExchangeClass = ccxtNamespace[exchangeId];
        if (typeof ExchangeClass === 'function') {
            return { ExchangeClass, exchangeId };
        }
    }

    throw new Error(
        `No Coinbase ${useSandbox ? 'sandbox' : 'production'} exchange class found in ccxt. ` +
        'Update ccxt with: npm install ccxt@latest'
    );
}
