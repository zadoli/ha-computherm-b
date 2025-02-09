# Computherm B Series Integration for Home Assistant

This is a Home Assistant integration for Computherm B Series WiFi thermostats. It provides control and monitoring capabilities through the official Computherm B Series cloud API.

## Features

- Support for multiple Computherm B Series devices under one account
- Real-time temperature and humidity (if supported) monitoring
- Target temperature control
- Function control (Heat/Cool/Off)
- Operation mode control (Auto/Manual/Off)
- Regular status updates via cloud polling
- Automatic device discovery

## Installation

### HACS Installation (CURRENTLY NOT AVAILABLE)

1. Open HACS in your Home Assistant instance
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add `https://github.com/zadoli/ha-computherm-b`
6. Select "Integration" as the category
7. Click "Add"
8. Find "Computherm B Series" in the integration list and click "Download"
9. Restart Home Assistant

### Manual Installation

1. Copy the `computherm_b` folder to your `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to Configuration > Integrations
2. Click the "+" button to add a new integration
3. Search for "Computherm B Series"
4. Enter your Computherm B Series account username and password
5. Click "Submit"
6. The integration will automatically discover and add all B Series devices associated with your account

[//]: # (## Supported Devices)

[//]: # ()
[//]: # (All Computherm B Series WiFi thermostats that can be controlled through the Computherm B Series mobile app are supported, including:)

[//]: # (- B Series WiFi Thermostats)

[//]: # (- Any future B Series compatible devices)

## Tested Devices
The tested devices had only one input sensor and one relay output, so the integration may not work (or only work with the "first") with devices that have more than one input and output.
- [Computherm B300](https://computherm.info/en/wi-fi_thermostats/computherm_b300)
- [Computherm B300RF](https://computherm.info/en/wi-fi_thermostats/computherm_b300rf)

## API Documentation

The integration uses the official Computherm B Series API:
- API Base URL: `https://api.computhermbseries.com`
- Reverse-engineered Websocket API: `wss://api.computhermbseries.com/socket.io/?EIO=4&transport=websocket`

## Error Handling

The integration includes robust error handling for common scenarios:
- Invalid credentials
- Network connectivity issues
- API rate limiting
- Device communication errors

## Contributing

Feel free to contribute to this project by:
- Reporting issues
- Suggesting enhancements
- Creating pull requests

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support with the Computherm B Series devices themselves, please contact Computherm support.
For integration-specific issues, please open an issue on GitHub.
