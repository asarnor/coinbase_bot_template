import ccxt from 'ccxt';
import { EMA, RSI, ATR } from 'technicalindicators';
import yargs from 'yargs';
import { hideBin } from 'yargs/helpers';

// --- CONFIGURATION ---
const symbol = 'ETH/USD';       // Coinbase uses USD, not USDT
const timeframe = '5m';         // Fast timeframe
const leverage = 5;             // 5x Leverage (for futures/advanced trade)
const riskPct = 0.20;           // Invest 20% of account balance
const atrMultiplier = 1.5;      // 1.5x Volatility Safety Net

// --- API KEYS (PASTE YOURS HERE) ---
// Coinbase Pro requires: API Key, Secret, and Passphrase
const apiKey = 'YOUR_API_KEY';
const apiSecret = 'YOUR_SECRET_KEY';
const apiPassphrase = 'YOUR_PASSPHRASE';  // Coinbase Pro passphrase

// Parse command line arguments
const argv = yargs(hideBin(process.argv))
    .option('test', {
        alias: 't',
        type: 'boolean',
        description: 'Run in test mode (single iteration, verbose output)',
        default: false
    })
    .option('sandbox', {
        alias: 's',
        type: 'boolean',
        description: 'Use sandbox environment',
        default: false
    })
    .option('execute', {
        alias: 'e',
        type: 'boolean',
        description: 'Enable actual trade execution (use with caution!)',
        default: false
    })
    .help()
    .alias('help', 'h')
    .argv;

// Determine if we should use sandbox
const useSandbox = argv.sandbox || argv.test;  // Auto-enable sandbox in test mode
const enableTrading = argv.execute;

// Get the exchange class - Use coinbaseexchange for sandbox support, coinbaseadvanced for production
const ExchangeClass = useSandbox ? (ccxt.coinbaseexchange || ccxt.coinbaseadvanced) : (ccxt.coinbaseadvanced || ccxt.coinbaseexchange);

if (argv.test) {
    console.log("🧪 TEST MODE ENABLED");
    console.log("=".repeat(60));
}

// API SETUP
let exchange;
try {
    exchange = new ExchangeClass({
        apiKey: apiKey,
        secret: apiSecret,
        password: apiPassphrase,  // Coinbase Pro requires passphrase
        enableRateLimit: true,
        sandbox: useSandbox,
    });
    
    // Check connection
    console.log(`🔌 Connecting to ${useSandbox ? 'SANDBOX' : 'PRODUCTION'}...`);
    await exchange.loadMarkets();
    console.log("✅ Connected to Coinbase Pro successfully.");
    
    if (argv.test) {
        console.log(`📊 Loaded ${Object.keys(exchange.markets).length} markets`);
        if (symbol in exchange.markets) {
            const marketInfo = exchange.markets[symbol];
            console.log(`✅ Symbol ${symbol} is available`);
            console.log(`   Market info: ${marketInfo.info?.display_name || 'N/A'}`);
        } else {
            console.log(`⚠️  Symbol ${symbol} not found in available markets`);
            const ethPairs = Object.keys(exchange.markets).filter(m => m.includes('ETH')).slice(0, 10);
            console.log("   Available ETH pairs:", ethPairs);
        }
    }
} catch (e) {
    console.log(`❌ Connection Error: ${e.message}`);
    console.log("Note: Coinbase Pro requires API Key, Secret, and Passphrase.");
    process.exit(1);
}

// Try setting leverage (Coinbase Advanced Trade supports futures)
try {
    // Coinbase Advanced Trade futures leverage setting
    await exchange.setLeverage(leverage, symbol);
    console.log(`⚡ Leverage set to ${leverage}x.`);
} catch (e) {
    console.log(`⚠️  Could not set leverage automatically: ${e.message}`);
    console.log("⚠️  Ensure leverage is set manually in Coinbase Advanced Trade, or use spot trading.");
}

// Helper function to convert OHLCV data to arrays for technical indicators
function prepareIndicatorData(ohlcv) {
    const closes = ohlcv.map(candle => candle[4]); // close price
    const highs = ohlcv.map(candle => candle[2]);   // high price
    const lows = ohlcv.map(candle => candle[3]);    // low price
    return { closes, highs, lows };
}

// Core functions
async function fetchData() {
    try {
        const bars = await exchange.fetchOHLCV(symbol, timeframe, undefined, 100);
        return bars;
    } catch (e) {
        console.log(`Data Error: ${e.message}`);
        return [];
    }
}

function analyzeMarket(ohlcv) {
    if (ohlcv.length < 20) {
        return null; // Not enough data
    }
    
    const { closes, highs, lows } = prepareIndicatorData(ohlcv);
    
    // Calculate indicators
    const ema20 = EMA.calculate({ period: 20, values: closes });
    const rsi = RSI.calculate({ period: 14, values: closes });
    const atr = ATR.calculate({ period: 14, high: highs, low: lows, close: closes });
    
    // Get latest values
    const latestIndex = ohlcv.length - 1;
    const price = closes[latestIndex];
    const ema20Value = ema20.length > 0 ? ema20[ema20.length - 1] : undefined;
    const rsiValue = rsi.length > 0 ? rsi[rsi.length - 1] : undefined;
    const atrValue = atr.length > 0 ? atr[atr.length - 1] : undefined;
    
    // Validate that all values are valid numbers
    if (typeof price !== 'number' || isNaN(price) || price <= 0) {
        return null;
    }
    if (typeof ema20Value !== 'number' || isNaN(ema20Value) || ema20Value <= 0) {
        return null;
    }
    if (typeof rsiValue !== 'number' || isNaN(rsiValue) || rsiValue < 0 || rsiValue > 100) {
        return null;
    }
    if (typeof atrValue !== 'number' || isNaN(atrValue) || atrValue <= 0) {
        return null;
    }
    
    return {
        price,
        ema20: ema20Value,
        rsi: rsiValue,
        atr: atrValue
    };
}

// Test balance fetching
async function testBalance() {
    try {
        console.log("\n💰 Testing Balance Fetch...");
        const balance = await exchange.fetchBalance();
        console.log("✅ Balance fetched successfully");
        
        // Show USD/USDC balance
        if (balance.USD) {
            const usdBalance = balance.USD;
            console.log(`   USD - Free: $${usdBalance.free.toFixed(2)}, Used: $${usdBalance.used.toFixed(2)}, Total: $${usdBalance.total.toFixed(2)}`);
        }
        
        if (balance.USDC) {
            const usdcBalance = balance.USDC;
            console.log(`   USDC - Free: $${usdcBalance.free.toFixed(2)}, Used: $${usdcBalance.used.toFixed(2)}, Total: $${usdcBalance.total.toFixed(2)}`);
        }
        
        return balance;
    } catch (e) {
        console.log(`❌ Balance Error: ${e.message}`);
        return null;
    }
}

// Test trade execution (dry run or actual)
async function testTradeExecution() {
    try {
        console.log("\n🧪 Testing Trade Execution...");
        
        // Fetch current price
        const ticker = await exchange.fetchTicker(symbol);
        const currentPrice = ticker.last;
        console.log(`   Current ${symbol} price: $${currentPrice.toFixed(2)}`);
        
        // Calculate position size
        const balance = await exchange.fetchBalance();
        const freeUsd = balance.USD?.free || balance.USDC?.free || 0;
        
        if (freeUsd === 0) {
            console.log("⚠️  No USD/USDC balance available for testing");
            return false;
        }
        
        const marginToUse = freeUsd * riskPct;
        const positionValue = marginToUse * leverage;
        const amountEth = positionValue / currentPrice;
        
        console.log(`   Calculated position size: ${amountEth.toFixed(6)} ${symbol.split('/')[0]}`);
        console.log(`   Margin to use: $${marginToUse.toFixed(2)}`);
        console.log(`   Position value (with ${leverage}x leverage): $${positionValue.toFixed(2)}`);
        
        if (enableTrading) {
            console.log(`\n⚠️  EXECUTING TEST TRADE (Sandbox: ${useSandbox})...`);
            console.log(`   Order: BUY ${amountEth.toFixed(6)} ${symbol} at market price`);
            
            // Execute test buy order
            try {
                const order = await exchange.createMarketBuyOrder(symbol, amountEth);
                console.log("✅ Order executed successfully!");
                console.log(`   Order ID: ${order.id || 'N/A'}`);
                console.log(`   Status: ${order.status || 'N/A'}`);
                console.log(`   Amount: ${order.amount || 'N/A'}`);
                console.log(`   Price: $${order.price || 'N/A'}`);
                
                // Try to cancel if in sandbox (for testing)
                if (useSandbox) {
                    await new Promise(resolve => setTimeout(resolve, 2000)); // Wait 2 seconds
                    try {
                        await exchange.cancelOrder(order.id, symbol);
                        console.log("✅ Test order cancelled (sandbox cleanup)");
                    } catch {
                        console.log("   (Order may have filled immediately)");
                    }
                }
                
                return true;
            } catch (e) {
                console.log(`❌ Trade execution failed: ${e.message}`);
                return false;
            }
        } else {
            console.log(`   (Trading disabled - use --execute flag to enable)`);
            console.log(`   Would execute: BUY ${amountEth.toFixed(6)} ${symbol}`);
            return true; // Test passed (dry run)
        }
    } catch (e) {
        console.log(`❌ Trade test error: ${e.message}`);
        return false;
    }
}

if (argv.test) {
    // Run comprehensive tests
    console.log("\n" + "=".repeat(60));
    console.log("RUNNING TESTS");
    console.log("=".repeat(60));
    
    // Test 1: Balance
    const balance = await testBalance();
    
    // Test 2: Data fetching
    console.log("\n📈 Testing Data Fetch...");
    try {
        const ohlcv = await fetchData();
        if (ohlcv.length > 0) {
            console.log(`✅ Data fetched successfully (${ohlcv.length} candles)`);
            console.log(`   Latest price: $${ohlcv[ohlcv.length - 1][4].toFixed(2)}`);
        } else {
            console.log("❌ No data returned");
        }
    } catch (e) {
        console.log(`❌ Data fetch error: ${e.message}`);
    }
    
    // Test 3: Market analysis
    console.log("\n🔍 Testing Market Analysis...");
    try {
        const ohlcv = await fetchData();
        if (ohlcv.length > 0) {
            const analysis = analyzeMarket(ohlcv);
            if (analysis) {
                console.log("✅ Analysis complete");
                console.log(`   Price: $${analysis.price.toFixed(2)}`);
                console.log(`   EMA 20: $${analysis.ema20.toFixed(2)}`);
                console.log(`   RSI: ${analysis.rsi.toFixed(2)}`);
                console.log(`   ATR: $${analysis.atr.toFixed(2)}`);
            } else {
                console.log("❌ Not enough data for analysis");
            }
        } else {
            console.log("❌ Cannot analyze - no data");
        }
    } catch (e) {
        console.log(`❌ Analysis error: ${e.message}`);
    }
    
    // Test 4: Trade execution
    if (balance) {
        await testTradeExecution();
    }
    
    console.log("\n" + "=".repeat(60));
    console.log("TEST COMPLETE");
    console.log("=".repeat(60));
    process.exit(0);
}

console.log(`🛡️ Active. Risking ${(riskPct * 100).toFixed(1)}% of balance per trade.`);
console.log(`📉 Crash Protection: ATR Trailing Stop active.`);
if (enableTrading) {
    console.log(`⚠️  TRADING ENABLED - Real orders will be executed!`);
} else {
    console.log(`ℹ️  Trading disabled - orders are simulated (use --execute to enable)`);
}

let inPosition = false;
let trailingStopPrice = 0.0;
let positionAmount = 0.0;  // Track position size for exit orders

async function getPositionSize(currentPrice) {
    try {
        const balance = await exchange.fetchBalance();
        // Coinbase uses USD instead of USDT
        const freeUsd = balance.USD?.free || balance.USDC?.free || 0;
        const marginToUse = freeUsd * riskPct;
        const positionValue = marginToUse * leverage;
        const amountEth = positionValue / currentPrice;
        return { amount: amountEth, cost: marginToUse };
    } catch (e) {
        console.log(`Balance Error: ${e.message}`);
        return { amount: 0, cost: 0 };
    }
}

// Sleep helper function
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// --- MAIN LOOP ---
while (true) {
    try {
        const ohlcv = await fetchData();
        if (ohlcv.length > 0) {
            const analysis = analyzeMarket(ohlcv);
            
            if (!analysis) {
                console.log("⚠️  Not enough data for analysis, waiting...");
                await sleep(60000);
                continue;
            }
            
            const { price, ema20, atr, rsi } = analysis;
            
            console.log(`Price: $${price.toFixed(2)} | RSI: ${rsi.toFixed(2)} | Stop: $${trailingStopPrice.toFixed(2)}`);
            
            // --- BUY LOGIC ---
            if (!inPosition) {
                // Trend Filter: Price > EMA 20 AND RSI > 50
                if (price > ema20 && rsi > 50) {
                    const { amount, cost } = await getPositionSize(price);
                    
                    if (amount > 0) {
                        console.log(`🚀 ENTER LONG: Buying ${amount.toFixed(4)} ETH (Cost: $${cost.toFixed(2)})`);
                        
                        if (enableTrading) {
                            try {
                                const order = await exchange.createMarketBuyOrder(symbol, amount);
                                console.log(`✅ Order executed: ${order.id || 'N/A'}`);
                            } catch (e) {
                                console.log(`❌ Order failed: ${e.message}`);
                                await sleep(60000);
                                continue; // Skip position update if order failed
                            }
                        } else {
                            console.log(`   (Simulated - use --execute to enable real trading)`);
                        }
                        
                        trailingStopPrice = price - (atr * atrMultiplier);
                        positionAmount = amount;  // Store position size for exit
                        inPosition = true;
                    }
                }
            }
            
            // --- SAFETY LOGIC ---
            else if (inPosition) {
                // Raise Safety Net
                const potentialStop = price - (atr * atrMultiplier);
                if (potentialStop > trailingStopPrice) {
                    trailingStopPrice = potentialStop;
                }
                
                // Crash Protection Trigger
                if (price <= trailingStopPrice) {
                    console.log(`🚨 STOP LOSS TRIGGERED at $${price.toFixed(2)}`);
                    
                    let orderSucceeded = false;
                    
                    if (enableTrading) {
                        try {
                            const order = await exchange.createMarketSellOrder(symbol, positionAmount);
                            console.log(`✅ Sell order executed: ${order.id || 'N/A'}`);
                            orderSucceeded = true;
                        } catch (e) {
                            console.log(`❌ Sell order failed: ${e.message}`);
                            // Don't reset position state if order failed - keep trying
                            await sleep(60000);
                            continue;
                        }
                    } else {
                        console.log(`   (Simulated - use --execute to enable real trading)`);
                        orderSucceeded = true; // In simulation mode, consider it successful
                    }
                    
                    // Only reset position state if order succeeded (or simulated)
                    if (orderSucceeded) {
                        inPosition = false;
                        trailingStopPrice = 0.0;
                        positionAmount = 0.0;
                    }
                }
            }
        }
    } catch (e) {
        console.log(`Error in main loop: ${e.message}`);
    }
    
    await sleep(60000); // Check every 60 seconds
}
