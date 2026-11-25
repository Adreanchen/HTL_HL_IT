package at.htlhl.weatherserver.repositories;

import java.sql.SQLException;

import javax.swing.tree.RowMapper;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import at.htlhl.weatherserver.model.Temperature;

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

    // API ********************************************************************

    public Temperature findLatesTemperature() {
        List<Temperature> temperatures = jdbcTemplate.
    }
}

private static class TemperatureRowMapper implements RowMapper<Temperature> {
    @Override
    public Temperature mapRow(ResultSet rs, int rowNum) throws SQLException {
        return null;
    }
}}