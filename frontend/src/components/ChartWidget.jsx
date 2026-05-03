import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CrosshairMode } from 'lightweight-charts';

export default function ChartWidget({ chartData, ticker, timeframe, isConnected, onSubscribe, indicatorConfig, indicatorVisibility, toggleIndicator }) {
    const [inputTicker, setInputTicker] = useState(ticker);

    useEffect(() => {
        setInputTicker(ticker);
    }, [ticker]);

    const mainContainerRef = useRef();
    const volContainerRef = useRef();

    const chartRefs = useRef({});
    const seriesRef = useRef({});
    const barsRef = useRef([]);
    const initialZoomRef = useRef(false);

    const [hoverTime, setHoverTime] = useState(null);
    const [latestBar, setLatestBar] = useState(null);
    const [volHeight, setVolHeight] = useState(160);
    const isDraggingVolRef = useRef(false);
    const dragStartYRef = useRef(0);
    const dragStartHeightRef = useRef(0);

    const applicableIndicators = indicatorConfig.filter(
        ind => ind.timeframes && ind.timeframes[timeframe] !== undefined
    );

    // Initialize charts once
    useEffect(() => {
        if (!mainContainerRef.current) return;

        const handleResize = () => {
            if (chartRefs.current.main) chartRefs.current.main.applyOptions({ width: mainContainerRef.current.clientWidth, height: mainContainerRef.current.clientHeight });
            if (chartRefs.current.vol) chartRefs.current.vol.applyOptions({ width: volContainerRef.current.clientWidth, height: volContainerRef.current.clientHeight });
        };

        const chartOptions = {
            layout: {
                background: { type: ColorType.Solid, color: '#ffffff' },
                textColor: '#787b86',
                fontFamily: "-apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, Ubuntu, sans-serif",
                fontSize: 12,
            },
            grid: {
                vertLines: { color: '#f0f3fa' },
                horzLines: { color: '#f0f3fa' },
            },
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: { color: '#9598a1', width: 1, style: 2, labelBackgroundColor: '#131722' },
                horzLine: { color: '#9598a1', width: 1, style: 2, labelBackgroundColor: '#131722' },
            },
            localization: {
                timeFormatter: (time) => {
                    const date = new Date(time * 1000);
                    return date.toLocaleString('en-US', { timeZone: 'America/New_York', hour12: false, year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                }
            },
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                borderColor: '#d1d4dc',
                tickMarkFormatter: (time, tickMarkType, locale) => {
                    const date = new Date(time * 1000);
                    if (tickMarkType <= 2) {
                        return date.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' });
                    }
                    return date.toLocaleString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false });
                }
            },
            rightPriceScale: {
                borderColor: '#d1d4dc',
                autoScale: true,
                entireTextOnly: false,
                minimumWidth: 50,
            },
        };

        const indicatorOptions = {
            ...chartOptions,
            layout: {
                ...chartOptions.layout,
                background: { type: ColorType.Solid, color: 'transparent' },
            },
            grid: {
                vertLines: { color: '#f0f3fa' },
                horzLines: { color: 'transparent' },
            },
            rightPriceScale: {
                borderColor: '#d1d4dc',
                autoScale: true,
                entireTextOnly: false,
                minimumWidth: 50,
            },
        };

        const mainChart = createChart(mainContainerRef.current, chartOptions);
        const volChart = createChart(volContainerRef.current, indicatorOptions);

        const syncAxisWidths = () => {
            const mainTable = mainContainerRef.current?.querySelector('table');
            const volTable = volContainerRef.current?.querySelector('table');
            if (!mainTable) return;

            const mainAxisTd = mainTable.querySelector('tr td:last-child');
            if (!mainAxisTd) return;
            const targetWidth = mainAxisTd.offsetWidth;
            if (targetWidth <= 0) return;

            if (volTable) {
                const axisTd = volTable.querySelector('tr td:last-child');
                if (axisTd && axisTd.offsetWidth !== targetWidth) {
                    axisTd.style.width = targetWidth + 'px';
                    axisTd.style.minWidth = targetWidth + 'px';
                    axisTd.style.maxWidth = targetWidth + 'px';
                }
            }
        };

        const axisInterval = setInterval(syncAxisWidths, 500);
        setTimeout(syncAxisWidths, 200);

        chartRefs.current = { main: mainChart, vol: volChart };

        // Background tint for extended hours
        const extBgOpts = {
            priceScaleId: '',
            scaleMargins: { top: 0, bottom: 0 },
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
        };
        const mainExtSeries = mainChart.addHistogramSeries(extBgOpts);
        const volExtSeries = volChart.addHistogramSeries(extBgOpts);

        const candleSeries = mainChart.addCandlestickSeries({
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderVisible: false,
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
        });

        const indicatorOpts = { crosshairMarkerVisible: false, autoscaleInfoProvider: () => null };

        seriesRef.current = { mainExtSeries, volExtSeries, candleSeries };

        // Sync Time Scales
        const syncTime = (source, target) => {
            source.timeScale().subscribeVisibleLogicalRangeChange((range) => {
                if (range) target.timeScale().setVisibleLogicalRange(range);
            });
        };
        syncTime(mainChart, volChart);
        syncTime(volChart, mainChart);

        mainChart.subscribeCrosshairMove((param) => {
            if (!param.time || param.point === undefined) {
                setHoverTime(null);
            } else {
                setHoverTime(param.time);
            }
        });

        window.addEventListener('resize', handleResize);
        setTimeout(handleResize, 100);

        return () => {
            clearInterval(axisInterval);
            window.removeEventListener('resize', handleResize);
            mainChart.remove();
            volChart.remove();
        };
    }, []);

    // Add indicator series when config loads (separate from chart init)
    useEffect(() => {
        if (!indicatorConfig.length || !chartRefs.current.main) return;

        const mainChart = chartRefs.current.main;
        const volChart = chartRefs.current.vol;
        const seriesMap = { ...seriesRef.current };

        const indicatorOpts = { crosshairMarkerVisible: false, autoscaleInfoProvider: () => null };
        const compactVolFormat = {
            type: 'custom',
            formatter: (val) => {
                if (val >= 1e6) return (val / 1e6).toFixed(2) + 'M';
                if (val >= 1e3) return (val / 1e3).toFixed(0) + 'K';
                return val.toFixed(0);
            },
            minMove: 1,
        };

        for (const ind of indicatorConfig) {
            if (seriesMap[ind.id]) continue; // already created
            if (ind.type === 'volume') {
                seriesMap[ind.id] = volChart.addHistogramSeries({
                    color: ind.color,
                    priceFormat: compactVolFormat,
                    priceScaleId: 'right',
                });
            } else {
                seriesMap[ind.id] = mainChart.addLineSeries({
                    color: ind.color,
                    lineWidth: ind.line_width || 1,
                    lineStyle: ind.line_style === 'dashed' ? 2 : 0,
                    priceLineVisible: ind.price_line_visible ?? false,
                    lastValueVisible: ind.last_value_visible ?? false,
                    title: ind.type === 'daily' ? ind.label : undefined,
                    ...indicatorOpts,
                });
            }
        }

        seriesRef.current = seriesMap;
    }, [indicatorConfig]);

    // Handle incoming data
    useEffect(() => {
        if (!chartData || !seriesRef.current.candleSeries) return;

        const seriesMap = seriesRef.current;
        const { mainExtSeries, volExtSeries, candleSeries } = seriesMap;

        if (chartData.type === 'history') {
            const bars = chartData.bars;
            barsRef.current = [...bars];
            setLatestBar(bars[bars.length - 1]);

            const candles = [];
            const volumePoints = [];
            const extPoints = [];
            const indicatorPoints = {};
            for (const ind of indicatorConfig) {
                indicatorPoints[ind.id] = [];
            }

            for (const bar of bars) {
                const t = Math.floor(bar.time);

                const isReg = bar.is_regular !== false;
                const tintColor = isReg ? 'rgba(0, 0, 0, 0)' : 'rgba(33, 150, 243, 0.08)';
                extPoints.push({ time: t, value: 1, color: tintColor });

                candles.push({ time: t, open: bar.open, high: bar.high, low: bar.low, close: bar.close });

                volumePoints.push({
                    time: t,
                    value: bar.volume,
                    color: bar.close >= bar.open ? 'rgba(8, 153, 129, 0.5)' : 'rgba(242, 54, 69, 0.5)'
                });

                for (const ind of indicatorConfig) {
                    const val = bar[ind.id];
                    if (val !== null && val !== undefined) {
                        indicatorPoints[ind.id].push({ time: t, value: val });
                    }
                }
            }

            mainExtSeries.setData(extPoints);
            volExtSeries.setData(extPoints);
            candleSeries.setData(candles);
            seriesMap.volume?.setData(volumePoints);

            for (const ind of indicatorConfig) {
                if (ind.type === 'volume') continue;
                const series = seriesMap[ind.id];
                if (series && indicatorPoints[ind.id].length > 0) {
                    series.setData(indicatorPoints[ind.id]);
                }
            }

            const totalBars = candles.length;
            if (totalBars > 0 && chartRefs.current.main && !initialZoomRef.current) {
                const defaultVisibleBars = 240;
                const timeScale = chartRefs.current.main.timeScale();
                timeScale.setVisibleLogicalRange({
                    from: Math.max(0, totalBars - defaultVisibleBars),
                    to: totalBars - 1
                });
                initialZoomRef.current = true;
            }

        } else if (chartData.type === 'update') {
            const bar = chartData.bar;
            const t = Math.floor(bar.time);

            const last = barsRef.current[barsRef.current.length - 1];
            if (last && last.time === bar.time) {
                barsRef.current[barsRef.current.length - 1] = bar;
            } else {
                barsRef.current.push(bar);
            }
            setLatestBar({ ...bar });

            const isReg = bar.is_regular !== false;
            const tintColor = isReg ? 'rgba(0, 0, 0, 0)' : 'rgba(33, 150, 243, 0.08)';

            mainExtSeries.update({ time: t, value: 1, color: tintColor });
            volExtSeries.update({ time: t, value: 1, color: tintColor });

            candleSeries.update({ time: t, open: bar.open, high: bar.high, low: bar.low, close: bar.close });

            seriesMap.volume?.update({
                time: t,
                value: bar.volume,
                color: bar.close >= bar.open ? 'rgba(8, 153, 129, 0.5)' : 'rgba(242, 54, 69, 0.5)'
            });

            for (const ind of indicatorConfig) {
                if (ind.type === 'volume') continue;
                const val = bar[ind.id];
                if (val !== null && val !== undefined) {
                    seriesMap[ind.id]?.update({ time: t, value: val });
                }
            }
        }
    }, [chartData]);

    // Handle clear on ticker/timeframe change
    useEffect(() => {
        barsRef.current = [];
        setLatestBar(null);
        setHoverTime(null);
        initialZoomRef.current = false;
        if (seriesRef.current.candleSeries) {
            for (const key of Object.keys(seriesRef.current)) {
                const s = seriesRef.current[key];
                if (s && typeof s.setData === 'function') {
                    s.setData([]);
                }
            }
        }
    }, [ticker, timeframe]);

    // Visibility toggles
    useEffect(() => {
        for (const ind of indicatorConfig) {
            const series = seriesRef.current[ind.id];
            if (series) {
                const shown = indicatorVisibility[ind.id] ?? false;
                series.applyOptions({ visible: shown });
            }
        }
    }, [indicatorVisibility, indicatorConfig]);

    // Update time axis visibility dynamically based on active panes
    const showVolume = indicatorVisibility.volume ?? true;
    useEffect(() => {
        if (chartRefs.current.main) {
            chartRefs.current.main.timeScale().applyOptions({ visible: !showVolume });
            chartRefs.current.vol.timeScale().applyOptions({ visible: showVolume });
        }
        const resize = () => window.dispatchEvent(new Event('resize'));
        setTimeout(resize, 50);
    }, [showVolume]);

    const handleZoomIn = () => {
        if (chartRefs.current.main) {
            const timeScale = chartRefs.current.main.timeScale();
            const range = timeScale.getVisibleLogicalRange();
            if (range) {
                const diff = (range.to - range.from) * 0.1;
                timeScale.setVisibleLogicalRange({ from: range.from + diff, to: range.to - diff });
            }
        }
    };

    const handleZoomOut = () => {
        if (chartRefs.current.main) {
            const timeScale = chartRefs.current.main.timeScale();
            const range = timeScale.getVisibleLogicalRange();
            if (range) {
                const diff = (range.to - range.from) * 0.1;
                timeScale.setVisibleLogicalRange({ from: range.from - diff, to: range.to + diff });
            }
        }
    };

    const handleScrollLeft = () => {
        if (chartRefs.current.main) {
            const timeScale = chartRefs.current.main.timeScale();
            const range = timeScale.getVisibleLogicalRange();
            if (range) {
                const shift = (range.to - range.from) * 0.1;
                timeScale.setVisibleLogicalRange({ from: range.from - shift, to: range.to - shift });
            }
        }
    };

    const handleScrollRight = () => {
        if (chartRefs.current.main) {
            const timeScale = chartRefs.current.main.timeScale();
            const range = timeScale.getVisibleLogicalRange();
            if (range) {
                const shift = (range.to - range.from) * 0.1;
                timeScale.setVisibleLogicalRange({ from: range.from + shift, to: range.to + shift });
            }
        }
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        if (inputTicker) onSubscribe(inputTicker, timeframe);
    };

    // Derived Display Data
    const displayBar = hoverTime
        ? barsRef.current.find(b => b.time === hoverTime)
        : latestBar;

    const prevBarIndex = displayBar ? barsRef.current.findIndex(b => b.time === displayBar.time) - 1 : -1;
    const prevBar = prevBarIndex >= 0 ? barsRef.current[prevBarIndex] : null;

    const formatPrice = (val) => val != null ? val.toFixed(2) : '-';
    const formatVol = (val) => {
        if (val == null) return '-';
        if (val >= 1e6) return (val / 1e6).toFixed(2) + 'M';
        if (val >= 1e3) return (val / 1e3).toFixed(2) + 'K';
        return val.toString();
    };

    let changeStr = '-';
    let changePctStr = '-';
    let changeColor = 'text-gray-500';

    if (displayBar && prevBar) {
        const change = displayBar.close - prevBar.close;
        const pct = (change / prevBar.close) * 100;
        const sign = change >= 0 ? '+' : '';
        changeStr = `${sign}${change.toFixed(2)}`;
        changePctStr = `(${sign}${pct.toFixed(2)}%)`;
        changeColor = change >= 0 ? 'text-green-500' : 'text-red-500';
    }

    const getDailyChange = () => {
        if (!barsRef.current.length || !latestBar) return null;

        const latestDate = new Date(barsRef.current[barsRef.current.length - 1].time * 1000).getDate();
        let prevClose = null;

        for (let i = barsRef.current.length - 1; i >= 0; i--) {
            const barDate = new Date(barsRef.current[i].time * 1000).getDate();
            if (barDate !== latestDate) {
                prevClose = barsRef.current[i].close;
                break;
            }
        }

        if (prevClose === null && barsRef.current.length > 0) {
            prevClose = barsRef.current[0].open;
        }

        if (prevClose !== null) {
            const dChange = latestBar.close - prevClose;
            const dPct = (dChange / prevClose) * 100;
            const dSign = dChange >= 0 ? '+' : '';
            return {
                changeStr: `${dSign}${dChange.toFixed(2)}`,
                pctStr: `(${dSign}${dPct.toFixed(2)}%)`,
                color: dChange >= 0 ? 'text-green-500' : 'text-red-500'
            };
        }
        return null;
    };
    const dailyChangeData = getDailyChange();

    const EyeIcon = ({ visible }) => (visible
        ? <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
        : <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" /></svg>
    );

    return (
        <div className="flex-1 flex flex-col w-full h-full bg-white relative">
            <style>{`
                #tv-attr-logo, .tv-lightweight-charts-logo { display: none !important; }
            `}</style>

            <div className="absolute top-4 left-4 z-0 pointer-events-none select-none text-gray-200 opacity-50 text-6xl font-bold tracking-widest uppercase">
                {ticker}
            </div>

            <div className="absolute top-4 left-4 z-20 flex flex-col gap-2">

                <div className="flex items-center gap-3 bg-white/90 px-3 py-2 rounded-lg border border-gray-200 backdrop-blur-sm shadow-sm">
                    <form onSubmit={handleSubmit} className="flex items-center space-x-2">
                        <input
                            type="text"
                            value={inputTicker}
                            onChange={(e) => setInputTicker(e.target.value.toUpperCase())}
                            placeholder="Ticker"
                            className="px-2 py-1 bg-white border border-gray-300 rounded text-sm text-gray-800 focus:outline-none focus:border-blue-500 uppercase w-24"
                        />
                        <select
                            value={timeframe}
                            onChange={(e) => onSubscribe(ticker, e.target.value)}
                            className="px-2 py-1 bg-white border border-gray-300 rounded text-sm text-gray-800 focus:outline-none focus:border-blue-500"
                        >
                            <option value="10s">10s</option>
                            <option value="1m">1m</option>
                            <option value="1d">1D</option>
                        </select>
                        <button type="submit" className="hidden">Load</button>
                    </form>

                    <div className="w-px h-5 bg-gray-300"></div>

                    {displayBar && (
                        <div className="flex items-center gap-3 tracking-wide font-mono text-[11px]">
                            <span className="text-gray-500">O <span className="text-gray-900">{formatPrice(displayBar.open)}</span></span>
                            <span className="text-gray-500">H <span className="text-gray-900">{formatPrice(displayBar.high)}</span></span>
                            <span className="text-gray-500">L <span className="text-gray-900">{formatPrice(displayBar.low)}</span></span>
                            <span className="text-gray-500">C <span className="text-gray-900">{formatPrice(displayBar.close)}</span></span>

                            <span className={`font-semibold ${changeColor}`} title="Bar Change">{changeStr} {changePctStr}</span>

                            {dailyChangeData && (
                                <span className={`font-semibold ml-2 ${dailyChangeData.color}`} title="Daily Change">
                                    Day: {dailyChangeData.changeStr} {dailyChangeData.pctStr}
                                </span>
                            )}

                            <span className="text-gray-500 ml-2">V <span className="text-gray-900">{formatVol(displayBar.volume)}</span></span>
                        </div>
                    )}

                    <div className="w-px h-5 bg-gray-300"></div>

                    <div className="flex items-center space-x-1.5" title={isConnected ? "Connected" : "Disconnected"}>
                        <div className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-red-500'}`}></div>
                    </div>
                </div>

                <div className="flex flex-col gap-0.5 mt-1">
                    {applicableIndicators.map(ind => {
                        const shown = indicatorVisibility[ind.id] ?? false;
                        const value = displayBar?.[ind.id];
                        return (
                            <div key={ind.id} className="flex items-center gap-1 group">
                                <button onClick={() => toggleIndicator(ind.id)} className="text-gray-400 hover:text-gray-700 focus:outline-none transition-colors">
                                    <EyeIcon visible={shown} />
                                </button>
                                <span className="text-[11px] font-medium" style={{ color: ind.color }}>{ind.label}</span>
                                {shown && value != null && <span className="text-[11px] font-mono" style={{ color: ind.color }}>{ind.type === 'volume' ? formatVol(value) : formatPrice(value)}</span>}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Chart Panes Layout */}
            <div className="flex-1 flex flex-col w-full h-full">
                <div className="flex-1 w-full relative" style={{ minHeight: 0 }}>
                    <div ref={mainContainerRef} className="absolute inset-0 w-full h-full" />

                    <div className="absolute bottom-2 right-0 w-[50px] flex justify-center z-20">
                        <button
                            onClick={() => {
                                if (chartRefs.current.main) {
                                    chartRefs.current.main.priceScale('right').applyOptions({ autoScale: true });
                                    const timeScale = chartRefs.current.main.timeScale();
                                    const totalBars = barsRef.current.length;
                                    if (totalBars > 0) {
                                        const visibleBars = 240;
                                        timeScale.setVisibleLogicalRange({ from: Math.max(0, totalBars - visibleBars), to: totalBars - 1 });
                                    }
                                }
                            }}
                            className="w-6 h-6 flex items-center justify-center text-[10px] font-bold text-[#2962ff] hover:text-[#1e4eb8] bg-white/80 hover:bg-white rounded shadow-sm border border-[#d1d4dc] cursor-pointer transition-all uppercase"
                            title="Auto Fit"
                        >
                            A
                        </button>
                    </div>

                    <div className="absolute bottom-2 left-1/2 -translate-x-1/2 z-20 flex items-center justify-center">
                        <div className="flex items-center gap-1 bg-transparent p-1 rounded-lg">
                            <button onClick={handleScrollLeft} className="p-1 px-2 hover:bg-gray-100/30 rounded text-[#787b86] transition-colors">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7"></path></svg>
                            </button>
                            <div className="w-px h-4 bg-[#d1d4dc]/30 mx-0.5"></div>
                            <button onClick={handleZoomOut} className="p-1 px-2 hover:bg-gray-100/30 rounded text-[#787b86] transition-colors font-bold text-base leading-none">-</button>
                            <button onClick={handleZoomIn} className="p-1 px-2 hover:bg-gray-100/30 rounded text-[#787b86] transition-colors font-bold text-base leading-none">+</button>
                            <div className="w-px h-4 bg-[#d1d4dc]/30 mx-0.5"></div>
                            <button onClick={handleScrollRight} className="p-1 px-2 hover:bg-gray-100/30 rounded text-[#787b86] transition-colors">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7"></path></svg>
                            </button>
                        </div>
                    </div>
                </div>

                {showVolume && (
                    <>
                        <div
                            className="w-full h-1.5 cursor-ns-resize flex items-center justify-center group"
                            style={{ background: '#f0f3fa', borderTop: '1px solid #d1d4dc' }}
                            onMouseDown={(e) => {
                                isDraggingVolRef.current = true;
                                dragStartYRef.current = e.clientY;
                                dragStartHeightRef.current = volHeight;
                                const onMove = (me) => {
                                    if (!isDraggingVolRef.current) return;
                                    const delta = dragStartYRef.current - me.clientY;
                                    setVolHeight(Math.max(60, dragStartHeightRef.current + delta));
                                    window.dispatchEvent(new Event('resize'));
                                };
                                const onUp = () => {
                                    isDraggingVolRef.current = false;
                                    window.removeEventListener('mousemove', onMove);
                                    window.removeEventListener('mouseup', onUp);
                                };
                                window.addEventListener('mousemove', onMove);
                                window.addEventListener('mouseup', onUp);
                            }}
                        >
                            <div className="w-8 h-0.5 bg-[#d1d4dc] group-hover:bg-[#9598a1] rounded-full transition-colors" />
                        </div>
                        <div ref={volContainerRef} style={{ height: volHeight }} className="w-full" />
                    </>
                )}
                {!showVolume && <div ref={volContainerRef} className="hidden" />}
            </div>

        </div>
    );
}
