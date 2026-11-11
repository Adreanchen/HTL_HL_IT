package at.htlhl.weatherserver.repositories;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class TemperatureRepository {

    // Constants **************************************************************

    private final static String SELECT_LATEST_TEMP_SQL = """
            SELECT measuretime, temp
            FROM TemperatureRepository
            ORDER BY measuretime DESC
            LIMIT 1
            """;

    // Fields *****************************************************************

    private JdbcTemplate jdbcTemplate;

    // Instance creation ******************************************************

    public TemperatureRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }
}