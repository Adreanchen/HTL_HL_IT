
1. Wählen Sie die first_name und die last_name jedes Schauspielers aus.
   Diese Abfrage sollte dazu führen, dass 2 Spalten ausgewählt werden.

   ```sql
   SELECT first_name, last_name FROM actor;
   ```

2. Wählen Sie den vollständigen Namen des Schauspielers.
   Diese Abfrage sollte in einer Spalte resultieren.

   ```sql
   SELECT first_name || ' ' || last_name AS full_name FROM actor;
   ```

3. Wähle die Schauspieler aus, deren Namen mit einem 'D' beginnen.

   ```sql
   SELECT * FROM actor WHERE first_name LIKE 'D%';
   ```

4. Wählen Sie alle Akteurinformationen nach aufsteigendem Vornamen aus.

   ```sql
   SELECT * FROM actor ORDER BY first_name ASC;
   ```

5. Zähle die Vornamen der einzigartigen Schauspieler

   ```sql
   SELECT COUNT(DISTINCT first_name) FROM actor;
   ```

6. Zählen Sie die Anzahl der Filme basierend auf ihrer Mietdauer.
   rental_duaration in der Filmtabelle bezieht sich darauf,
   wie lange die DVD ausgeliehen werden darf.

   ```sql
   SELECT rental_duration, COUNT(*) AS film_count FROM film GROUP BY rental_duration;
   ```

7. Wählen Sie den maximalen Ersatzpreis

   ```sql
   SELECT MAX(replacement_cost) FROM film;
   ```

8. Wählen Sie die Titel der Filme aus, die den höchsten Ersatzpreis haben.

   ```sql
   SELECT title FROM film WHERE replacement_cost = (SELECT MAX(replacement_cost) FROM film);
   ```

9. Wählen Sie die einzigartigen verschiedenen Bewertungen für die Filme in der Filmtafel aus.

   ```sql
   SELECT DISTINCT rating FROM film;
   ```

10. Wählen Sie die Anzahl der verfügbaren Filme unter jedem rating aus.

    ```sql
    SELECT rating, COUNT(*) AS film_count FROM film GROUP BY rating;
    ```

11. Ändere die Filmsprache für die ersten 20 Filme von Englisch auf Italienisch.

    ```sql
    UPDATE film SET language_id = 2 WHERE film_id IN (SELECT film_id FROM film ORDER BY film_id LIMIT 20);
    ```

12. Wählen Sie die Anzahl der Filme nach Sprache gruppiert

    ```sql
    SELECT language_id, COUNT(*) AS film_countFROM FROM film GROUP BY language_id;
    ```

13. Wählen Sie die Sprache, zu der die meisten Filme gehören.

    ```sql
    SELECT l.name, COUNT(f.film_id) AS film_count FROM film f JOIN language l ON f.language_id = l.language_id GROUP BY l.name ORDER BY film_count DESC LIMIT 1;
    ```

14. Filmtitel sowie Ersatzkosten und Bewertungen auswählen sowie
    den durchschnittlichen Ersatzpreis für Filme in der Bewertung,
    zu der der Film gehört.

    ```sql
    SELECT title, replacement_cost, rating, AVG(replacement_cost) OVER (PARTITION BY rating) AS avg_replacement_cost_per_rating FROM film;
    ```

15. Wählen Sie die Bewertungen und durchschnittlichen Ersatzkosten
    für italienische Filme aus.

    ```sql
    SELECT f.rating, AVG(f.replacement_cost) AS avg_replacement_cost FROM film f JOIN language l ON f.language_id = l.language_id WHERE LOWER(TRIM(l.name)) = 'italian' GROUP BY f.rating;
    ```

16. Zählen Sie die Filme mit der maximalen replacement_cost in der Filmtabelle.

    ```sql
    SELECT COUNT(*) FROM film WHERE replacement_cost = (SELECT MAX(replacement_cost) FROM film);
    ```

17. Zähle die Anzahl der Filme, die wir für jede Sprache in der Filmtabelle haben.
       (Beachten Sie, dass wir Filme haben, die nur auf Englisch und Italienisch sind).

    ```sql
    SELECT l.name, COUNT(f.film_id) AS film_count FROM film f JOIN language l ON f.language_id = l.language_id GROUP BY l.name;
    ```

18. Zähle die Anzahl der Filme, die unter jeder der 6 Sprachen existieren,
    die in der Sprachtabelle existieren (Englisch, Italienisch, Französisch,
    Mandarin, Japanisch und Deutsch).

    ```sql
    SELECT l.name, COUNT(f.film_id) AS film_count FROM language l LEFT JOIN film f ON l.language_id = f.language_id GROUP BY l.language_id, l.name;
    ```

19. Zähle die Anzahl der Filme nach language_id und Bewertung und sortiere die Ergebnisse nach
    aufsteigender Sprache.

    ```sql
    SELECT language_id, rating, COUNT(*) AS film_count FROM film GROUP BY language_id, rating ORDER BY language_id ASC;
    ```














​	
