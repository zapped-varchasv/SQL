-- SQLite 3.25+. SUM(counts)/SUM(denominator), never AVG(published percentages).
CREATE VIEW v_route_detail AS
SELECT f.*,d.year,d.month_number,d.month_label,a.airline,r.route,r.origin,r.destination
FROM fact_route_month f JOIN dim_date d ON d.date=f.date
JOIN dim_airline a USING(airline_id) JOIN dim_route r USING(route_id);

CREATE VIEW v_monthly AS
SELECT date,year,month_number,month_label,SUM(scheduled) scheduled,SUM(flown) flown,
 SUM(cancelled) cancelled,SUM(arr_on_time) arr_on_time,SUM(dep_on_time) dep_on_time,
 SUM(arr_delayed) arr_delayed,
 1.0*SUM(cancelled)/NULLIF(SUM(scheduled),0) cancellation_rate,
 1.0*SUM(arr_on_time)/NULLIF(SUM(flown),0) arrival_otp,
 1.0*SUM(dep_on_time)/NULLIF(SUM(flown),0) departure_otp
FROM v_route_detail GROUP BY date;

CREATE VIEW v_annual AS
SELECT year,SUM(scheduled) scheduled,SUM(flown) flown,SUM(cancelled) cancelled,
 SUM(arr_on_time) arr_on_time,SUM(arr_delayed) arr_delayed,
 1.0*SUM(cancelled)/NULLIF(SUM(scheduled),0) cancellation_rate,
 1.0*SUM(arr_on_time)/NULLIF(SUM(flown),0) arrival_otp,
 1.0*SUM(dep_on_time)/NULLIF(SUM(flown),0) departure_otp
FROM v_route_detail GROUP BY year;

CREATE VIEW v_route_priority AS
WITH route_year AS (
 SELECT year,route_id,route,origin,destination,COUNT(DISTINCT date) months_reported,
 SUM(scheduled) scheduled,SUM(flown) flown,SUM(cancelled) cancelled,
 SUM(arr_on_time) arr_on_time,SUM(arr_delayed) arr_delayed,
 1.0*SUM(cancelled)/NULLIF(SUM(scheduled),0) cancellation_rate,
 1.0*SUM(arr_on_time)/NULLIF(SUM(flown),0) arrival_otp
 FROM v_route_detail GROUP BY year,route_id
), ranked AS (
 SELECT *,DENSE_RANK() OVER(PARTITION BY year ORDER BY cancelled DESC) cancellation_rank,
 SUM(cancelled) OVER(PARTITION BY year) year_cancellations,
 SUM(cancelled) OVER(PARTITION BY year ORDER BY cancelled DESC,route ROWS UNBOUNDED PRECEDING) cumulative_cancellations
 FROM route_year
)
SELECT *,1.0*cancelled/NULLIF(year_cancellations,0) share_of_cancellations,
 1.0*cumulative_cancellations/NULLIF(year_cancellations,0) cumulative_share,
 CASE WHEN months_reported<12 THEN 'Partial year: review coverage'
      WHEN scheduled<1000 THEN 'Low volume: interpret cautiously'
      ELSE 'Full year / 1,000+ scheduled' END coverage_note
FROM ranked;

-- Fixed route cohort: all 12 months in BOTH 2024 and 2025. This controls route
-- presence, not airline mix, weather, flight timing or passenger volume.
CREATE VIEW v_matched_yoy AS
WITH eligible AS (
 SELECT route_id FROM v_route_priority WHERE year IN(2024,2025)
 GROUP BY route_id HAVING COUNT(*)=2 AND MIN(months_reported)=12
), annual AS (
 SELECT year,COUNT(DISTINCT route_id) routes,SUM(scheduled) scheduled,
 SUM(flown) flown,SUM(cancelled) cancelled,SUM(arr_on_time) arr_on_time,
 1.0*SUM(cancelled)/NULLIF(SUM(scheduled),0) cancellation_rate,
 1.0*SUM(arr_on_time)/NULLIF(SUM(flown),0) arrival_otp
 FROM v_route_detail JOIN eligible USING(route_id)
 WHERE year IN(2024,2025) GROUP BY year
)
SELECT *,100*(cancellation_rate-LAG(cancellation_rate) OVER(ORDER BY year)) cancellation_change_pp,
 100*(arrival_otp-LAG(arrival_otp) OVER(ORDER BY year)) arrival_change_pp
FROM annual;

CREATE VIEW v_rolling AS
SELECT *,1.0*SUM(cancelled) OVER w / NULLIF(SUM(scheduled) OVER w,0) cancellation_rate_3m,
 1.0*SUM(arr_on_time) OVER w / NULLIF(SUM(flown) OVER w,0) arrival_otp_3m,
 COUNT(*) OVER w months_in_window
FROM v_monthly WINDOW w AS (ORDER BY date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW);

CREATE VIEW v_airline_year AS
SELECT year,airline,SUM(scheduled) scheduled,SUM(flown) flown,SUM(cancelled) cancelled,
 SUM(arr_on_time) arr_on_time,SUM(arr_delayed) arr_delayed,
 1.0*SUM(cancelled)/NULLIF(SUM(scheduled),0) cancellation_rate,
 1.0*SUM(arr_on_time)/NULLIF(SUM(flown),0) arrival_otp
FROM v_route_detail GROUP BY year,airline;

CREATE VIEW v_network_annual AS
SELECT d.year,SUM(n.scheduled) scheduled,SUM(n.flown) flown,SUM(n.cancelled) cancelled,
 1.0*SUM(n.cancelled)/NULLIF(SUM(n.scheduled),0) cancellation_rate,
 1.0*SUM(n.arr_on_time)/NULLIF(SUM(n.flown),0) arrival_otp,
 1.0*SUM(n.dep_on_time)/NULLIF(SUM(n.flown),0) departure_otp
FROM network_month n JOIN dim_date d ON n.date=d.date GROUP BY d.year;
