PRAGMA foreign_keys = ON;
CREATE TABLE dim_date (
 date TEXT PRIMARY KEY, year INTEGER NOT NULL, month_number INTEGER NOT NULL,
 month_label TEXT NOT NULL, quarter TEXT NOT NULL
);
CREATE TABLE dim_airline (airline_id INTEGER PRIMARY KEY, airline TEXT UNIQUE NOT NULL);
CREATE TABLE dim_route (
 route_id INTEGER PRIMARY KEY, route TEXT UNIQUE NOT NULL,
 origin TEXT NOT NULL, destination TEXT NOT NULL
);
-- One row per month, airline and directional reporting route. Never load totals here.
CREATE TABLE fact_route_month (
 date TEXT REFERENCES dim_date(date), airline_id INTEGER REFERENCES dim_airline(airline_id),
 route_id INTEGER REFERENCES dim_route(route_id),
 scheduled INTEGER NOT NULL CHECK(scheduled>=0), flown INTEGER NOT NULL CHECK(flown>=0),
 cancelled INTEGER NOT NULL CHECK(cancelled>=0), dep_on_time INTEGER NOT NULL,
 arr_on_time INTEGER NOT NULL, dep_delayed INTEGER NOT NULL, arr_delayed INTEGER NOT NULL,
 PRIMARY KEY(date,airline_id,route_id), CHECK(scheduled=flown+cancelled),
 CHECK(dep_on_time+dep_delayed=flown), CHECK(arr_on_time+arr_delayed=flown)
);
-- Published entire-network benchmark, a separate grain and scope.
CREATE TABLE network_month (
 date TEXT PRIMARY KEY REFERENCES dim_date(date), scheduled INTEGER NOT NULL,
 flown INTEGER NOT NULL, cancelled INTEGER NOT NULL, dep_on_time INTEGER NOT NULL,
 arr_on_time INTEGER NOT NULL, dep_delayed INTEGER NOT NULL, arr_delayed INTEGER NOT NULL
);
CREATE INDEX ix_route_month ON fact_route_month(route_id,date);
