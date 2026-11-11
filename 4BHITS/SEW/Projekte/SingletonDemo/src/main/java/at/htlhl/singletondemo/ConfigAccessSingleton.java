package at.htlhl.singletondemo;

/**
 * Usage example for singelton implementation
 *
 * Example demonstrates a single resource (e.g. a file) access
 */
public class ConfigAccessSingleton {
    private static ConfigAccessSingleton instance;

    /**
     * PRIVATE constructor
     */

    private ConfigAccessSingleton() {}

    /**
     * Create (once) and return the sigleton instanze
     * <br>
     * Note the keywords static and synchronized (needed for thread safety)
     *
     * @return instance
     */
    public static synchronized ConfigAccessSingleton getInstanze() {
        if (instance == null) {
            instance = new ConfigAccessSingleton();
        }
        return instance;
    }

    // Example methods to access Values in an imagined configuration file

    /**
     * Read a setting from the configuration file
     * <br>
     * (not implemented)
     * @return 67
     */
    public int readSettingOne() {
        return 67;
    }

    public void writeSettingOne(int settingOne) {
        //
    }
}
