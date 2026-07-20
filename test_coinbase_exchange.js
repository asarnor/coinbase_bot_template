import test from 'node:test';
import assert from 'node:assert/strict';

import { resolveCoinbaseExchange } from './coinbase_exchange.js';


class Coinbase {}
class CoinbaseAdvanced {}
class CoinbaseExchange {}


test('production prefers the current Coinbase Advanced Trade class', () => {
    const resolved = resolveCoinbaseExchange(
        {
            coinbase: Coinbase,
            coinbaseadvanced: CoinbaseAdvanced,
            coinbaseexchange: CoinbaseExchange,
        },
        false
    );

    assert.equal(resolved.ExchangeClass, Coinbase);
    assert.equal(resolved.exchangeId, 'coinbase');
});


test('production supports older Advanced Trade aliases', () => {
    const resolved = resolveCoinbaseExchange(
        {
            coinbaseadvanced: CoinbaseAdvanced,
            coinbaseexchange: CoinbaseExchange,
        },
        false
    );

    assert.equal(resolved.ExchangeClass, CoinbaseAdvanced);
    assert.equal(resolved.exchangeId, 'coinbaseadvanced');
});


test('sandbox uses only the Exchange sandbox implementation', () => {
    const resolved = resolveCoinbaseExchange(
        {
            coinbase: Coinbase,
            coinbaseexchange: CoinbaseExchange,
        },
        true
    );

    assert.equal(resolved.ExchangeClass, CoinbaseExchange);
    assert.equal(resolved.exchangeId, 'coinbaseexchange');
});


test('sandbox fails closed when its implementation is unavailable', () => {
    assert.throws(
        () => resolveCoinbaseExchange({ coinbase: Coinbase }, true),
        /No Coinbase sandbox exchange class/
    );
});


test('production reports a clear error when ccxt has no Coinbase class', () => {
    assert.throws(
        () => resolveCoinbaseExchange({}, false),
        /No Coinbase production exchange class/
    );
});
