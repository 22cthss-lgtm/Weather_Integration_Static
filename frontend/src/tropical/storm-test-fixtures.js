// Test-only storm files. Values are copied from the real S6a samples (fetchers/tests/fixtures/tropical,
// CEMPAKA on 2026-11-11 and PENA 04C warning #23 on 2026-11-12) as produced by the backend parsers;
// the CWA past track is cut to its last two points. Not imported by application code.
// Sources: JTWC (17 U.S.C. §403), 出典：気象庁ホームページ（加工して作成）, 交通部中央氣象署 W-C0034-005.

const CEMPAKA_ANALYSIS = {
  "schema_version": 1,
  "cyclone_id": "2026-jma-tc2638",
  "fetched_at": "2026-11-11T10:30:00Z",
  "agencies": {
    "jtwc": {
      "product_url": "https://www.metoc.navy.mil/jtwc/products/wp3126.tcw",
      "graphic_url": "https://www.metoc.navy.mil/jtwc/products/wp3126.gif",
      "issued_at": "2026-11-11T09:00:00Z",
      "bulletin": "021",
      "final": false,
      "fix": {
        "analysis_time": "2026-11-11T06:00:00Z",
        "lat": 29.1,
        "lon": 150.2,
        "category": "TYPHOON",
        "max_wind": {
          "kt": 65,
          "ms": null,
          "averaging_min": 1
        },
        "gust": {
          "kt": 80,
          "ms": null
        },
        "pressure_hpa": 983,
        "movement": {
          "direction_deg": 70,
          "direction_text": null,
          "speed_kt": 33,
          "speed_kmh": null
        },
        "radii": [
          {
            "threshold": {
              "value": 64,
              "unit": "kt"
            },
            "unit": "nm",
            "sectors": [
              {
                "dir": "NE",
                "radius": 20
              },
              {
                "dir": "SE",
                "radius": 30
              },
              {
                "dir": "SW",
                "radius": 25
              },
              {
                "dir": "NW",
                "radius": 20
              }
            ]
          },
          {
            "threshold": {
              "value": 50,
              "unit": "kt"
            },
            "unit": "nm",
            "sectors": [
              {
                "dir": "NE",
                "radius": 45
              },
              {
                "dir": "SE",
                "radius": 50
              },
              {
                "dir": "SW",
                "radius": 40
              },
              {
                "dir": "NW",
                "radius": 35
              }
            ]
          },
          {
            "threshold": {
              "value": 34,
              "unit": "kt"
            },
            "unit": "nm",
            "sectors": [
              {
                "dir": "NE",
                "radius": 100
              },
              {
                "dir": "SE",
                "radius": 105
              },
              {
                "dir": "SW",
                "radius": 95
              },
              {
                "dir": "NW",
                "radius": 70
              }
            ]
          }
        ]
      },
      "past_track_origin": "accumulated",
      "past_track": []
    },
    "jma": {
      "product_url": "https://www.data.jma.go.jp/developer/xml/data/20261111094118_0_VPTW60_010000.xml",
      "graphic_url": null,
      "issued_at": "2026-11-11T09:45:00Z",
      "bulletin": "52",
      "final": false,
      "fix": {
        "analysis_time": "2026-11-11T09:00:00Z",
        "lat": 29.2,
        "lon": 151.0,
        "category": "STS",
        "max_wind": {
          "kt": 60,
          "ms": 30,
          "averaging_min": 10
        },
        "gust": {
          "kt": 85,
          "ms": 45
        },
        "pressure_hpa": 985,
        "movement": {
          "direction_deg": null,
          "direction_text": "ENE",
          "speed_kt": 27,
          "speed_kmh": 50
        },
        "radii": [
          {
            "threshold": {
              "value": 50,
              "unit": "kt"
            },
            "unit": "nm",
            "sectors": [
              {
                "dir": "ALL",
                "radius": 60
              }
            ]
          },
          {
            "threshold": {
              "value": 30,
              "unit": "kt"
            },
            "unit": "nm",
            "sectors": [
              {
                "dir": "ALL",
                "radius": 150
              }
            ]
          }
        ]
      },
      "past_track_origin": "accumulated",
      "past_track": []
    },
    "cwa": {
      "product_url": "https://opendata.cwa.gov.tw/dataset/warning/W-C0034-005",
      "graphic_url": null,
      "issued_at": "2026-11-11T06:00:00Z",
      "bulletin": null,
      "final": false,
      "fix": {
        "analysis_time": "2026-11-11T06:00:00Z",
        "lat": 28.9,
        "lon": 149.9,
        "category": null,
        "max_wind": {
          "kt": null,
          "ms": 30,
          "averaging_min": 10
        },
        "gust": {
          "kt": null,
          "ms": 38
        },
        "pressure_hpa": 975,
        "movement": {
          "direction_deg": null,
          "direction_text": "ENE",
          "speed_kt": null,
          "speed_kmh": 54
        },
        "radii": [
          {
            "threshold": {
              "value": 25,
              "unit": "m/s"
            },
            "unit": "km",
            "sectors": [
              {
                "dir": "NE",
                "radius": 60
              },
              {
                "dir": "SE",
                "radius": 40
              },
              {
                "dir": "SW",
                "radius": 40
              },
              {
                "dir": "NW",
                "radius": 50
              }
            ]
          },
          {
            "threshold": {
              "value": 15,
              "unit": "m/s"
            },
            "unit": "km",
            "sectors": [
              {
                "dir": "NE",
                "radius": 180
              },
              {
                "dir": "SE",
                "radius": 120
              },
              {
                "dir": "SW",
                "radius": 120
              },
              {
                "dir": "NW",
                "radius": 160
              }
            ]
          }
        ]
      },
      "past_track_origin": "source",
      "past_track": [
        {
          "analysis_time": "2026-11-10T18:00:00Z",
          "lat": 26.8,
          "lon": 144.3,
          "category": null,
          "max_wind": {
            "kt": null,
            "ms": 35,
            "averaging_min": 10
          },
          "pressure_hpa": 965
        },
        {
          "analysis_time": "2026-11-11T00:00:00Z",
          "lat": 27.7,
          "lon": 146.9,
          "category": null,
          "max_wind": {
            "kt": null,
            "ms": 33,
            "averaging_min": 10
          },
          "pressure_hpa": 970
        }
      ]
    }
  }
};

const CEMPAKA_FORECAST = {
  "schema_version": 1,
  "cyclone_id": "2026-jma-tc2638",
  "fetched_at": "2026-11-11T10:30:00Z",
  "agencies": {
    "jtwc": {
      "product_url": "https://www.metoc.navy.mil/jtwc/products/wp3126.tcw",
      "issued_at": "2026-11-11T09:00:00Z",
      "bulletin": "021",
      "init_time": "2026-11-11T06:00:00Z",
      "points": [
        {
          "tau_h": 12,
          "valid_time": "2026-11-11T18:00:00Z",
          "lat": 31.2,
          "lon": 157.0,
          "category": null,
          "max_wind": {
            "kt": 55,
            "ms": null,
            "averaging_min": 1
          },
          "gust": null,
          "pressure_hpa": null,
          "probability_circle": null,
          "radii": [
            {
              "threshold": {
                "value": 50,
                "unit": "kt"
              },
              "unit": "nm",
              "sectors": [
                {
                  "dir": "NE",
                  "radius": 35
                },
                {
                  "dir": "SE",
                  "radius": 35
                },
                {
                  "dir": "SW",
                  "radius": 40
                },
                {
                  "dir": "NW",
                  "radius": 20
                }
              ]
            },
            {
              "threshold": {
                "value": 34,
                "unit": "kt"
              },
              "unit": "nm",
              "sectors": [
                {
                  "dir": "NE",
                  "radius": 170
                },
                {
                  "dir": "SE",
                  "radius": 130
                },
                {
                  "dir": "SW",
                  "radius": 130
                },
                {
                  "dir": "NW",
                  "radius": 90
                }
              ]
            }
          ],
          "note": "DISSIPATING"
        },
        {
          "tau_h": 24,
          "valid_time": "2026-11-12T06:00:00Z",
          "lat": 33.6,
          "lon": 164.2,
          "category": null,
          "max_wind": {
            "kt": 45,
            "ms": null,
            "averaging_min": 1
          },
          "gust": null,
          "pressure_hpa": null,
          "probability_circle": null,
          "radii": [
            {
              "threshold": {
                "value": 34,
                "unit": "kt"
              },
              "unit": "nm",
              "sectors": [
                {
                  "dir": "NE",
                  "radius": 180
                },
                {
                  "dir": "SE",
                  "radius": 135
                },
                {
                  "dir": "SW",
                  "radius": 130
                },
                {
                  "dir": "NW",
                  "radius": 90
                }
              ]
            }
          ],
          "note": "DISSIPATED"
        }
      ]
    },
    "jma": {
      "product_url": "https://www.data.jma.go.jp/developer/xml/data/20261111094118_0_VPTW60_010000.xml",
      "issued_at": "2026-11-11T09:45:00Z",
      "bulletin": "52",
      "init_time": "2026-11-11T09:00:00Z",
      "points": [
        {
          "tau_h": 12,
          "valid_time": "2026-11-11T21:00:00Z",
          "lat": 32.1,
          "lon": 158.6,
          "category": "LOW",
          "max_wind": {
            "kt": 55,
            "ms": 30,
            "averaging_min": 10
          },
          "gust": {
            "kt": 80,
            "ms": 40
          },
          "pressure_hpa": 990,
          "probability_circle": {
            "radius": 85,
            "unit": "km",
            "probability_pct": 70
          },
          "radii": [],
          "note": null
        },
        {
          "tau_h": 24,
          "valid_time": "2026-11-12T09:00:00Z",
          "lat": 37.6,
          "lon": 168.7,
          "category": "LOW",
          "max_wind": {
            "kt": 55,
            "ms": 30,
            "averaging_min": 10
          },
          "gust": {
            "kt": 80,
            "ms": 40
          },
          "pressure_hpa": 992,
          "probability_circle": {
            "radius": 120,
            "unit": "km",
            "probability_pct": 70
          },
          "radii": [],
          "note": null
        }
      ]
    },
    "cwa": {
      "product_url": "https://opendata.cwa.gov.tw/dataset/warning/W-C0034-005",
      "issued_at": "2026-11-11T06:00:00Z",
      "bulletin": null,
      "init_time": "2026-11-11T06:00:00Z",
      "points": [
        {
          "tau_h": 6,
          "valid_time": "2026-11-11T12:00:00Z",
          "lat": 30.2,
          "lon": 153.7,
          "category": null,
          "max_wind": {
            "kt": null,
            "ms": 25,
            "averaging_min": 10
          },
          "gust": {
            "kt": null,
            "ms": 33
          },
          "pressure_hpa": 985,
          "probability_circle": {
            "radius": 40,
            "unit": "km",
            "probability_pct": 70
          },
          "radii": [
            {
              "threshold": {
                "value": 15,
                "unit": "m/s"
              },
              "unit": "km",
              "sectors": [
                {
                  "dir": "ALL",
                  "radius": 150
                }
              ]
            }
          ],
          "note": null
        },
        {
          "tau_h": 12,
          "valid_time": "2026-11-11T18:00:00Z",
          "lat": 31.6,
          "lon": 157.7,
          "category": null,
          "max_wind": null,
          "gust": null,
          "pressure_hpa": 988,
          "probability_circle": {
            "radius": 70,
            "unit": "km",
            "probability_pct": 70
          },
          "radii": [],
          "note": "EXTRATROPICAL"
        }
      ]
    }
  }
};

const PENA_ANALYSIS = {
  "schema_version": 1,
  "cyclone_id": "2026-jtwc-04c",
  "fetched_at": "2026-11-12T10:30:07Z",
  "agencies": {
    "jtwc": {
      "product_url": "https://www.metoc.navy.mil/jtwc/products/cp0426.tcw",
      "graphic_url": null,
      "issued_at": "2026-11-12T10:00:00Z",
      "bulletin": "023",
      "final": false,
      "fix": {
        "analysis_time": "2026-11-12T06:00:00Z",
        "lat": 9.8,
        "lon": -171.3,
        "category": "TROPICAL DEPRESSION",
        "max_wind": {
          "kt": 35,
          "ms": null,
          "averaging_min": 1
        },
        "gust": {
          "kt": 45,
          "ms": null
        },
        "pressure_hpa": 1006,
        "movement": {
          "direction_deg": 270,
          "direction_text": null,
          "speed_kt": 14,
          "speed_kmh": null
        },
        "radii": [
          {
            "threshold": {
              "value": 34,
              "unit": "kt"
            },
            "unit": "nm",
            "sectors": [
              {
                "dir": "NE",
                "radius": 100
              },
              {
                "dir": "SE",
                "radius": null
              },
              {
                "dir": "SW",
                "radius": null
              },
              {
                "dir": "NW",
                "radius": null
              }
            ]
          }
        ]
      },
      "past_track_origin": "accumulated",
      "past_track": []
    },
    "jma": null,
    "cwa": null
  }
};

const PENA_FORECAST = {
  "schema_version": 1,
  "cyclone_id": "2026-jtwc-04c",
  "fetched_at": "2026-11-12T10:30:07Z",
  "agencies": {
    "jtwc": {
      "product_url": "https://www.metoc.navy.mil/jtwc/products/cp0426.tcw",
      "issued_at": "2026-11-12T10:00:00Z",
      "bulletin": "023",
      "init_time": "2026-11-12T06:00:00Z",
      "points": [
        {
          "tau_h": 12,
          "valid_time": "2026-11-12T18:00:00Z",
          "lat": 9.9,
          "lon": -174.3,
          "category": null,
          "max_wind": {
            "kt": 30,
            "ms": null,
            "averaging_min": 1
          },
          "gust": null,
          "pressure_hpa": null,
          "probability_circle": null,
          "radii": [],
          "note": null
        },
        {
          "tau_h": 24,
          "valid_time": "2026-11-13T06:00:00Z",
          "lat": 10.0,
          "lon": -177.4,
          "category": null,
          "max_wind": {
            "kt": 30,
            "ms": null,
            "averaging_min": 1
          },
          "gust": null,
          "pressure_hpa": null,
          "probability_circle": null,
          "radii": [],
          "note": "POST_TROPICAL"
        },
        {
          "tau_h": 36,
          "valid_time": "2026-11-13T18:00:00Z",
          "lat": 10.2,
          "lon": -180.0,
          "category": null,
          "max_wind": {
            "kt": 30,
            "ms": null,
            "averaging_min": 1
          },
          "gust": null,
          "pressure_hpa": null,
          "probability_circle": null,
          "radii": [],
          "note": "POST_TROPICAL"
        }
      ]
    },
    "jma": null,
    "cwa": null
  }
};

const clone = value => JSON.parse(JSON.stringify(value));

export const cempakaAnalysis = () => clone(CEMPAKA_ANALYSIS);
export const cempakaForecast = () => clone(CEMPAKA_FORECAST);
export const penaAnalysis = () => clone(PENA_ANALYSIS);
export const penaForecast = () => clone(PENA_FORECAST);
