import React from "react";
import {HelpPopup, humanFileSize, PageContainer, TabLinks, useTitle, WROLModeMessage} from "./Common";
import {Route, Routes} from "react-router-dom";
import {getMapImportStatus, importMapFiles} from "../api";
import {
    Checkbox,
    Loader as SLoader,
    PlaceholderLine,
    TableBody,
    TableCell,
    TableFooter,
    TableHeader,
    TableHeaderCell,
    TableRow
} from "semantic-ui-react";
import Message from "semantic-ui-react/dist/commonjs/collections/Message";
import {Button, Icon, Loader, Placeholder, Table} from "./Theme";

class ManageMap extends React.Component {
    constructor(props) {
        super(props);
        this.state = {
            files: null,
            importing: null,
            import_running: false,
            selectedPaths: [],
            dockerized: null,
        }
    }

    async componentDidMount() {
        await this.fetchImportStatus();
        this.intervalId = setInterval(this.fetchImportStatus, 1000 * 30);
    }

    componentWillUnmount() {
        clearInterval(this.intervalId);
    }

    fetchImportStatus = async () => {
        try {
            const importStatus = await getMapImportStatus();
            this.setState({
                files: importStatus['files'],
                importing: importStatus['importing'],
                import_running: importStatus['import_running'],
                dockerized: importStatus['dockerized'],
            });
        } catch (e) {
            console.error(e);
        }
    }

    import = async (e) => {
        e.preventDefault();

        this.setState({'ready': false});
        const {files, selectedPaths} = this.state;
        if (!selectedPaths || selectedPaths.length === 0) {
            // No files are selected, import all.
            let paths = [];
            for (let i = 0; i < files.length; i++) {
                paths = paths.concat([files[i].path]);
            }
            await importMapFiles(paths);
        } else {
            await importMapFiles(selectedPaths);
        }
        await this.fetchImportStatus();
    }

    handleCheckbox = (checked, pbf) => {
        let {selectedPaths} = this.state;
        if (checked === true) {
            selectedPaths = selectedPaths.concat([pbf.path]);
        } else {
            const index = selectedPaths.indexOf(pbf.path);
            if (index > -1) {
                selectedPaths.splice(index, 1);
            }
        }
        this.setState({selectedPaths});
    }

    tableRow = (pbf, disabled) => {
        let ref = React.createRef();
        const {size, path, imported, time_to_import} = pbf;
        let sizeCells = (<>
            <TableCell>{humanFileSize(size)}</TableCell>
            <TableCell>{humanFileSize(size * 25)}</TableCell>
            <TableCell>{time_to_import}</TableCell>
        </>);
        return <TableRow key={path}>
            <TableCell collapsing>
                <Checkbox
                    disabled={disabled}
                    ref={ref}
                    onChange={(e, data) => this.handleCheckbox(data.checked, pbf)}
                />
            </TableCell>
            <TableCell>
                <a href={`/media/${path}`}>{path}</a>
            </TableCell>
            <TableCell>
                {path === this.state.importing ?
                    <SLoader active inline size='mini'/> :
                    imported ? 'yes' : 'no'}
            </TableCell>
            {size !== null ? sizeCells : <TableCell colSpan={3}/>}
        </TableRow>
    }

    render() {
        const {files, selectedPaths, import_running, importing, dockerized} = this.state;

        let dockerWarning;
        if (dockerized === true) {
            dockerWarning = <Message negative icon>
                <Icon name='hand point right'/>
                <Message.Content>
                    <Message.Header>
                        Maps are not fully supported in a Docker container!
                    </Message.Header>

                    <p><b>Only one PBF can be imported and displayed in the docker container.</b></p>

                    <p>To import a map file, run the following docker-compose commands:</p>
                    <pre>  docker-compose stop map</pre>
                    <pre>  docker-compose rm map</pre>
                    <pre>  docker-compose run --rm -v /absolute/path/to/map.osm.pbf:/data.osm.pbf
                        -v openstreetmap-data:/var/lib/postgresql/12/main map import
                    </pre>

                    <p>Be sure to change <b>/absolute/path/to/map.osm.pbf</b>!</p>

                    <p>After you have imported a new PBF file, you need to clear the rendered tile cache:</p>
                    <pre>  docker volume rm openstreetmap-rendered-tiles</pre>
                    <pre>  docker volume create openstreetmap-rendered-tiles</pre>

                    <p>Start your map container:</p>
                    <pre>  docker-compose up -d map</pre>
                </Message.Content>
            </Message>
        }

        let downloadMessage = <Message info icon>
            <Icon name='question'/>
            <Message.Content>
                <Message.Header>
                    Where do I get map files?
                </Message.Header>

                <p>You can download map files from&nbsp;
                    <a href='https://download.geofabrik.de/'>https://download.geofabrik.de/</a>
                </p>

                <p><b>Download only the areas you need</b>. Large regions like all of Asia, or the entire
                    planet are most likely <b>too large</b> and won't render quickly. I recommend only
                    importing files less than 1GB on a Raspberry Pi.</p>

                <p>Only <b>*.osm.pbf</b> files are supported!</p>

                <p>Place downloaded map files into <b>map/pbf</b> so they can be imported here.</p>
            </Message.Content>
        </Message>

        let importingLoader = (
            <Loader size='large' active={import_running} inline='centered'>Importing: {importing}</Loader>
        );

        let disabled = dockerized || !files || files.length === 0 || import_running;
        let importButton = <Button
            primary
            disabled={disabled}
            onClick={this.import}
        >
            {selectedPaths.length > 0 ? 'Import Selected' : 'Import All'}
        </Button>;

        let rows;
        if (!files) {
            // Fetch request is not complete.
            rows = <TableRow>
                <TableCell/>
                <TableCell colSpan={6}>
                    <Placeholder>
                        <PlaceholderLine/>
                        <PlaceholderLine/>
                    </Placeholder>
                </TableCell>
            </TableRow>;
        } else if (files.length === 0) {
            rows = <TableRow>
                <TableCell/><TableCell colSpan={5}>No PBF map files were found in <b>map/pbf</b></TableCell>
            </TableRow>;
        } else {
            rows = files.map(i => this.tableRow(i, disabled));
        }

        let spaceHelpPopup = <HelpPopup
            content='Upon importing, a PBF file will consume more disk space than the original file.'/>;
        let timeHelpPopup = <HelpPopup content='Estimated for a Raspberry Pi 4'/>;

        return <PageContainer>
            <WROLModeMessage content='Cannot modify Map'/>
            {dockerWarning}
            {downloadMessage}
            {importingLoader}
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHeaderCell/>
                        <TableHeaderCell>PBF File</TableHeaderCell>
                        <TableHeaderCell>Imported</TableHeaderCell>
                        <TableHeaderCell>Size</TableHeaderCell>
                        <TableHeaderCell>Space Required {spaceHelpPopup}</TableHeaderCell>
                        <TableHeaderCell>Time to Import {timeHelpPopup}</TableHeaderCell>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {rows}
                </TableBody>
                <TableFooter>
                    <TableRow>
                        <TableHeaderCell/>
                        <TableHeaderCell colSpan={5}>
                            {importButton}
                        </TableHeaderCell>
                    </TableRow>
                </TableFooter>
            </Table>
        </PageContainer>
    }
}

function MapApp() {
    return (
        <iframe
            title='map'
            src={`http://${window.location.hostname}:8084/`}
            style={{
                position: 'fixed',
                height: '100%',
                width: '100%',
                border: 'none',
            }}/>
    )
}

export function MapRoute() {
    useTitle('Map');

    const links = [
        {text: 'Map', to: '/map', key: 'map', end: true},
        {text: 'Manage', to: '/map/manage', key: 'manage'},
    ];

    return <div style={{marginTop: '2em'}}>
        <TabLinks links={links}/>
        <Routes>
            <Route path='/' exact element={<MapApp/>}/>
            <Route path='manage' exact element={<ManageMap/>}/>
        </Routes>
    </div>
}
