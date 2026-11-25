package at.htlhl.weatherserver.repositories;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import at.htlhl.weatherserver.model.Temperature;

@Repository
public class TemperatureRepository {

    // Constants **************************************************************

    private static final String SELECT_LATEST_TEMP_SQL = """
            SELECT id, measuretime, temp
            FROM temperature
            ORDER BY measuretime DESC
            LIMIT 1
            """;

    // Fields *****************************************************************

    private final JdbcTemplate jdbcTemplate;

    // Instance creation ******************************************************

    public TemperatureRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    // API ********************************************************************

    public Temperature findLatestTemperature() {
        List<Temperature> temperatures = jdbcTemplate.query(SELECT_LATEST_TEMP_SQL, new TemperatureRowMapper());
        return temperatures.isEmpty() ? null : temperatures.getFirst();
    }

    private static class TemperatureRowMapper implements RowMapper<Temperature> {
        @Override
        public Temperature mapRow(ResultSet rs, int rowNum) throws SQLException {
            Temperature temperature = new Temperature();
            temperature.setId(rs.getLong("id"));
            temperature.setMeasureTime(rs.getTimestamp("measuretime").toLocalDateTime());
            temperature.setTemp(rs.getFloat("temp"));

            return temperature;
        }
    }
}