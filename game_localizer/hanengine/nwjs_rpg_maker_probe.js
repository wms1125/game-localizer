(function () {
    "use strict";

    var config = window.HANENGINE_NWJS_PROBE_CONFIG;
    var fs = require("fs");
    var path = require("path");
    var crypto = require("crypto");
    var runtimeEvents = [];
    var screenshots = [];
    var originalConsoleError = console.error;

    function eventText(value) {
        try {
            return typeof value === "string" ? value : JSON.stringify(value);
        } catch (_error) {
            return String(value);
        }
    }

    console.error = function () {
        runtimeEvents.push({
            kind: "console.error",
            message: Array.prototype.map.call(arguments, eventText).join(" ")
        });
        originalConsoleError.apply(console, arguments);
    };
    window.addEventListener("error", function (event) {
        runtimeEvents.push({
            kind: "window.error",
            message: event.message || "unknown window error",
            source: event.filename || null,
            line: event.lineno || null,
            column: event.colno || null
        });
    });
    window.addEventListener("unhandledrejection", function (event) {
        runtimeEvents.push({
            kind: "unhandledrejection",
            message: eventText(event.reason)
        });
    });

    function waitFor(read, accept, timeoutMs, description) {
        return new Promise(function (resolve, reject) {
            var started = Date.now();
            var timer = setInterval(function () {
                var value;
                try {
                    value = read();
                } catch (_error) {
                    value = null;
                }
                if (accept(value)) {
                    clearInterval(timer);
                    resolve(value);
                } else if (Date.now() - started >= timeoutMs) {
                    clearInterval(timer);
                    var detail = typeof description === "function"
                        ? description()
                        : description;
                    reject(new Error("timed out waiting for " + detail));
                }
            }, 100);
        });
    }

    function delay(milliseconds) {
        return new Promise(function (resolve) {
            setTimeout(resolve, milliseconds);
        });
    }

    function sha256(buffer) {
        return crypto.createHash("sha256").update(buffer).digest("hex");
    }

    function ensureDirectory(directory) {
        if (fs.existsSync(directory)) {
            return;
        }
        ensureDirectory(path.dirname(directory));
        fs.mkdirSync(directory);
    }

    function capturePage(relativePath) {
        return new Promise(function (resolve, reject) {
            try {
                nw.Window.get().capturePage(function (buffer) {
                    try {
                        var destination = path.join(config.output, relativePath);
                        ensureDirectory(path.dirname(destination));
                        fs.writeFileSync(destination, buffer);
                        var result = {
                            file: relativePath.replace(/\\/g, "/"),
                            sha256: sha256(buffer),
                            size_bytes: buffer.length
                        };
                        screenshots.push(result);
                        resolve(result);
                    } catch (error) {
                        reject(error);
                    }
                }, { format: "png", datatype: "buffer" });
            } catch (error) {
                reject(error);
            }
        });
    }

    function stopVideo() {
        if (!window.Graphics || !Graphics._video) {
            return;
        }
        Graphics._video.pause();
        Graphics._video.style.opacity = 0;
        Graphics._videoLoading = false;
    }

    function seekVideo(video, seconds) {
        return new Promise(function (resolve, reject) {
            var timeout = setTimeout(function () {
                reject(new Error("timed out seeking video"));
            }, 10000);
            function finish() {
                clearTimeout(timeout);
                video.removeEventListener("seeked", finish);
                resolve();
            }
            video.pause();
            video.addEventListener("seeked", finish);
            video.currentTime = Math.min(seconds, video.duration - 0.05);
        });
    }

    function normalizedVideoPath(video) {
        var source = video.currentSrc || video.src || "";
        try {
            return decodeURIComponent(new URL(source, window.location.href).pathname)
                .replace(/\\/g, "/");
        } catch (_error) {
            return decodeURIComponent(source).replace(/\\/g, "/");
        }
    }

    function loadedExpectedVideo(video, expectedPath) {
        var loadedPath = normalizedVideoPath(video);
        return !Graphics._videoLoading &&
            video.readyState >= 2 &&
            Boolean(video.duration) &&
            (loadedPath === expectedPath || loadedPath.slice(-(expectedPath.length + 1)) === "/" + expectedPath);
    }

    function playVideoAsset(asset) {
        stopVideo();
        var messageBusyBefore = $gameMessage.isBusy();
        if (messageBusyBefore) {
            $gameMessage.clear();
        }
        var interpreter = new Game_Interpreter();
        interpreter._params = [asset.movie_name];
        interpreter.command261();
        return waitFor(function () {
            var video = Graphics._video;
            if (!video || !loadedExpectedVideo(video, asset.path)) {
                return null;
            }
            return video;
        }, function (video) {
            return Boolean(video);
        }, 20000, function () {
            var video = Graphics._video;
            return "video " + asset.path +
                " (loaded_path=" + (video ? normalizedVideoPath(video) : "none") +
                ", loading=" + Graphics._videoLoading +
                ", ready_state=" + (video ? video.readyState : "none") + ")";
        }).then(function (video) {
            var result = {
                path: asset.path,
                loaded_path: normalizedVideoPath(video).slice(-asset.path.length),
                command_code: 261,
                message_busy_before: messageBusyBefore,
                status: "passed",
                duration: video.duration,
                width: video.videoWidth,
                height: video.videoHeight,
                segments: []
            };
            var chain = Promise.resolve();
            asset.segments.forEach(function (segment) {
                chain = chain.then(function () {
                    return seekVideo(video, segment.midpoint_seconds);
                }).then(function () {
                    Graphics._video.style.opacity = 1;
                    return delay(200);
                }).then(function () {
                    return capturePage(segment.screenshot_file);
                }).then(function (capture) {
                    result.segments.push({
                        segment_id: segment.segment_id,
                        midpoint_seconds: segment.midpoint_seconds,
                        observed_time: video.currentTime,
                        screenshot: capture
                    });
                });
            });
            return chain.then(function () {
                stopVideo();
                return result;
            });
        });
    }

    function titleState() {
        if (!window.SceneManager || !SceneManager._scene) {
            return null;
        }
        return {
            scene: SceneManager._scene.constructor.name,
            loaded: Boolean(window.$dataActors && window.$dataEnemies && window.$dataSystem)
        };
    }

    function mapState() {
        if (!window.SceneManager || !SceneManager._scene || !window.$gameMap) {
            return null;
        }
        return {
            scene: SceneManager._scene.constructor.name,
            map_id: $gameMap.mapId(),
            player_x: window.$gamePlayer && $gamePlayer.x,
            player_y: window.$gamePlayer && $gamePlayer.y
        };
    }

    function writeFailure(error) {
        ensureDirectory(config.output);
        fs.writeFileSync(
            path.join(config.output, "failure.json"),
            JSON.stringify({
                label: config.label,
                error: error && error.stack ? error.stack : String(error),
                runtime_events: runtimeEvents
            }, null, 2) + "\n",
            "utf8"
        );
    }

    ensureDirectory(config.output);
    var titleWaitState;
    var titleObservation;
    var mapWaitState;
    var mapObservation;
    var videoRuns = [];
    waitFor(titleState, function (value) {
        return value && value.scene === "Scene_Title" && value.loaded;
    }, 30000, "the loaded title scene").then(function (value) {
        titleWaitState = value;
        return delay(1000);
    }).then(function () {
        titleObservation = {
            document_title: document.title,
            scene: SceneManager._scene.constructor.name,
            game_title: $dataSystem.gameTitle,
            actors: $dataActors.filter(Boolean).filter(function (item) {
                return Boolean(item.name);
            }).map(function (item) {
                return { id: item.id, name: item.name };
            }),
            enemies: $dataEnemies.filter(Boolean).filter(function (item) {
                return Boolean(item.name);
            }).map(function (item) {
                return { id: item.id, name: item.name };
            }),
            font_ready: document.fonts
                ? document.fonts.check("28px GameFont", "汉化测试·♫")
                : null
        };
        return capturePage("title.png");
    }).then(function () {
        DataManager.setupNewGame();
        SceneManager.goto(Scene_Map);
        return waitFor(mapState, function (value) {
            return value && value.scene === "Scene_Map" && value.map_id > 0;
        }, 30000, "a non-zero new-game map");
    }).then(function (value) {
        mapWaitState = value;
        return delay(1000);
    }).then(function () {
        stopVideo();
        mapObservation = {
            scene: SceneManager._scene.constructor.name,
            map_id: $gameMap.mapId(),
            map_name: $dataMap.displayName,
            player_x: $gamePlayer.x,
            player_y: $gamePlayer.y,
            party_actor_names: $gameParty.members().map(function (actor) {
                return actor.name();
            })
        };
        return delay(200);
    }).then(function () {
        return capturePage("map.png");
    }).then(function () {
        var chain = Promise.resolve();
        config.video_assets.forEach(function (asset) {
            chain = chain.then(function () {
                return playVideoAsset(asset);
            }).then(function (result) {
                videoRuns.push(result);
            });
        });
        return chain;
    }).then(function () {
        var report = {
            schema_version: "hanengine.nwjs-rpg-maker-probe/v3",
            created_at: new Date().toISOString(),
            label: config.label,
            runtime_versions: process.versions,
            title_wait_state: titleWaitState,
            title_observation: titleObservation,
            map_wait_state: mapWaitState,
            map_observation: mapObservation,
            video_runs: videoRuns,
            screenshots: screenshots,
            runtime_events: runtimeEvents
        };
        fs.writeFileSync(
            path.join(config.output, "report.json"),
            JSON.stringify(report, null, 2) + "\n",
            "utf8"
        );
        setTimeout(function () {
            nw.App.quit();
        }, 500);
    }).catch(function (error) {
        writeFailure(error);
        setTimeout(function () {
            nw.App.quit();
        }, 500);
    });
}());
